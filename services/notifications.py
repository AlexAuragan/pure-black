import time
from typing import Any, TypedDict

from fabric.core.service import Property, Service, Signal
from gi.repository import Gio, GLib
from loguru import logger

from config.notification_filters import NotificationFilters
from services.hyprland import HyprlandManager

NOTIFICATIONS_BUS_NAME = "org.freedesktop.Notifications"
NOTIFICATIONS_BUS_PATH = "/org/freedesktop/Notifications"

NOTIFICATIONS_IFACE_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg direction="in"  type="s" name="app_name"/>
      <arg direction="in"  type="u" name="replaces_id"/>
      <arg direction="in"  type="s" name="app_icon"/>
      <arg direction="in"  type="s" name="summary"/>
      <arg direction="in"  type="s" name="body"/>
      <arg direction="in"  type="as" name="actions"/>
      <arg direction="in"  type="a{sv}" name="hints"/>
      <arg direction="in"  type="i" name="expire_timeout"/>
      <arg direction="out" type="u" name="id"/>
    </method>
    <method name="CloseNotification">
      <arg direction="in" type="u" name="id"/>
    </method>
    <method name="GetCapabilities">
      <arg direction="out" type="as" name="caps"/>
    </method>
    <method name="GetServerInformation">
      <arg direction="out" type="s" name="name"/>
      <arg direction="out" type="s" name="vendor"/>
      <arg direction="out" type="s" name="version"/>
      <arg direction="out" type="s" name="spec_version"/>
    </method>
    <signal name="NotificationClosed">
      <arg type="u" name="id"/>
      <arg type="u" name="reason"/>
    </signal>
    <signal name="ActionInvoked">
      <arg type="u" name="id"/>
      <arg type="s" name="action_key"/>
    </signal>
  </interface>
</node>
"""

# Reason codes per spec
REASON_EXPIRED = 1
REASON_DISMISSED = 2
REASON_CLOSED_BY_APP = 3
REASON_UNDEFINED = 4


class Notification(TypedDict):
    id: int
    app_name: str
    app_icon: str
    summary: str
    body: str
    actions: list[str]
    hints: dict[str, Any]
    expire_timeout: int  # ms; -1 = server default, 0 = permanent
    timestamp: float
    is_permanent: bool
    is_transient: bool  # show toast but don't persist in NC


class NotificationService(Service):
    @Signal
    def notification_added(self, notification_id: int) -> None: ...

    @Signal
    def notification_closed(self, notification_id: int, reason: int) -> None: ...

    @Signal
    def notification_group_changed(self, app_name: str) -> None: ...

    @Signal
    def changed(self) -> None: ...

    def __init__(self, hyprland: HyprlandManager | None = None, **kwargs: Any):
        super().__init__(**kwargs)

        # notifications grouped by app_name; order within a group is insertion order
        self._groups: dict[str, list[Notification]] = {}
        # fast lookup by id
        self._by_id: dict[int, Notification] = {}
        self._next_id: int = 1

        # per-notification GLib timeout source ids
        self._expire_sources: dict[int, int] = {}

        self._filters = NotificationFilters()
        self._connection: Gio.DBusConnection | None = None
        try:
            self._iface_node = Gio.DBusNodeInfo.new_for_xml(NOTIFICATIONS_IFACE_XML)
        except Exception as e:
            logger.error(f"[Notifications] failed to parse DBus interface XML: {e}")
            raise

        self._hyprland = hyprland
        if hyprland is not None:
            hyprland.connect("notify::active_windows", self._on_active_windows_changed)

        Gio.bus_own_name(
            Gio.BusType.SESSION,
            NOTIFICATIONS_BUS_NAME,
            Gio.BusNameOwnerFlags.REPLACE,
            self._on_bus_acquired,
            None,
            lambda *_: logger.warning("[Notifications] could not own DBus name — another daemon is running"),
        )

    # ------------------------------------------------------------------ props

    @Property(dict, "readable")
    def groups(self) -> dict[str, list[Notification]]:
        return self._groups

    @Property(list, "readable")
    def all_notifications(self) -> list[Notification]:
        result: list[Notification] = []
        for group in self._groups.values():
            result.extend(group)
        result.sort(key=lambda n: n["timestamp"])
        return result

    # ------------------------------------------------------------------ public api

    def close_notification(self, notification_id: int, reason: int = REASON_DISMISSED) -> None:
        notif = self._by_id.pop(notification_id, None)
        if notif is None:
            return

        self._cancel_expire(notification_id)

        group = self._groups.get(notif["app_name"], [])
        try:
            group.remove(notif)
        except ValueError:
            pass
        if not group:
            self._groups.pop(notif["app_name"], None)

        self._emit_dbus_signal("NotificationClosed", GLib.Variant("(uu)", (notification_id, reason)))
        self.notification_closed(notification_id, reason)
        self.notification_group_changed(notif["app_name"])
        self.changed()

    def close_group(self, app_name: str, reason: int = REASON_DISMISSED) -> None:
        ids = [n["id"] for n in self._groups.get(app_name, [])]
        for nid in ids:
            self.close_notification(nid, reason)

    def invoke_action(self, notification_id: int, action_key: str) -> None:
        if notification_id not in self._by_id:
            return
        self._emit_dbus_signal("ActionInvoked", GLib.Variant("(us)", (notification_id, action_key)))

    # ------------------------------------------------------------------ dbus server

    def _on_bus_acquired(self, conn: Gio.DBusConnection, name: str, _=None) -> None:
        self._connection = conn
        iface = self._iface_node.interfaces[0]
        conn.register_object(
            NOTIFICATIONS_BUS_PATH,
            iface,
            self._handle_method_call,
            None,
            None,
        )
        logger.info("[Notifications] DBus server registered")

    def _handle_method_call(
        self,
        conn: Gio.DBusConnection,
        sender: str,
        path: str,
        interface: str,
        method: str,
        params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
        _=None,
    ) -> None:
        match method:
            case "Notify":
                nid = self._handle_notify(params.unpack())
                invocation.return_value(GLib.Variant("(u)", (nid,)))

            case "CloseNotification":
                (nid,) = params.unpack()
                self.close_notification(nid, REASON_CLOSED_BY_APP)
                invocation.return_value(None)

            case "GetCapabilities":
                caps = ["body", "body-markup", "actions", "persistence", "icon-static", "icon-multi", "image/svg+xml"]
                invocation.return_value(GLib.Variant("(as)", (caps,)))

            case "GetServerInformation":
                invocation.return_value(GLib.Variant("(ssss)", ("FabricRice", "AlexAuragan", "0.1.0", "1.2")))

            case _:
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.UnknownMethod",
                    f"Unknown method: {method}",
                )

    def _handle_notify(self, args: tuple) -> int:
        app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout = args

        hints_unpacked: dict[str, Any] = {}
        if hints:
            for k, v in hints.items():
                try:
                    hints_unpacked[k] = v if not hasattr(v, "unpack") else v.unpack()
                except Exception:
                    hints_unpacked[k] = str(v)

        # tag-based replacement (x-canonical-private-synchronous)
        sync_tag = hints_unpacked.get("x-canonical-private-synchronous")
        if sync_tag and not replaces_id:
            for existing in list(self._by_id.values()):
                if existing["hints"].get("x-canonical-private-synchronous") == sync_tag:
                    replaces_id = existing["id"]
                    break

        # reuse id when replacing
        if replaces_id and replaces_id in self._by_id:
            nid = replaces_id
            self._cancel_expire(nid)
            old = self._by_id[nid]
            group = self._groups.get(old["app_name"], [])
            try:
                group.remove(old)
            except ValueError:
                pass
        else:
            nid = self._next_id
            self._next_id += 1

        urgency = hints_unpacked.get("urgency", 1)
        is_permanent = expire_timeout == 0
        is_transient = bool(hints_unpacked.get("transient", False)) or urgency == 0

        # build a temporary notif for filter matching before committing
        notif: Notification = {
            "id": nid,
            "app_name": app_name or "unknown",
            "app_icon": app_icon or "",
            "summary": summary or "",
            "body": body or "",
            "actions": list(actions) if actions else [],
            "hints": hints_unpacked,
            "expire_timeout": expire_timeout,
            "timestamp": time.time(),
            "is_permanent": is_permanent,
            "is_transient": is_transient,
        }

        # apply filter rules
        filter_action = self._filters.apply(notif)
        if filter_action == "drop":
            logger.debug(f"[Notifications] dropped #{nid} from '{app_name}' by filter rule")
            return nid
        if filter_action == "transient":
            notif["is_transient"] = True

        self._by_id[nid] = notif

        if not notif["is_transient"]:
            group = self._groups.setdefault(notif["app_name"], [])
            group.append(notif)
            self.notification_group_changed(notif["app_name"])

        self._schedule_expire(notif)

        self.notification_added(nid)
        self.changed()

        logger.debug(f"[Notifications] +{nid} from '{app_name}': {summary!r}")
        return nid

    # ------------------------------------------------------------------ expiry

    def _schedule_expire(self, notif: Notification) -> None:
        timeout = notif["expire_timeout"]
        nid = notif["id"]

        if timeout == 0:
            # permanent — never auto-expire
            return

        # -1 means server decides; use 5 s as default
        ms = timeout if timeout > 0 else 5000

        source_id = GLib.timeout_add(ms, self._on_expire, nid)
        self._expire_sources[nid] = source_id

    def _cancel_expire(self, nid: int) -> None:
        source_id = self._expire_sources.pop(nid, None)
        if source_id is not None:
            GLib.source_remove(source_id)

    def _on_expire(self, nid: int) -> bool:
        self._expire_sources.pop(nid, None)
        self.close_notification(nid, REASON_EXPIRED)
        return False  # don't repeat

    # ------------------------------------------------------------------ hyprland integration

    def _on_active_windows_changed(self, hyprland: HyprlandManager, *_) -> None:
        active_windows = hyprland.active_windows or {}
        for _mon_id, win in active_windows.items():
            if win is None:
                continue
            win_class = (win.get("class") or "").lower()
            win_title = (win.get("title") or "").lower()
            if not win_class and not win_title:
                continue
            for app_name in list(self._groups.keys()):
                if self._app_name_matches_window(app_name, win_class, win_title):
                    self._dismiss_transient_in_group(app_name)

    def _app_name_matches_window(self, app_name: str, win_class: str, win_title: str) -> bool:
        name = app_name.lower()
        return name in win_class or win_class in name or name in win_title

    def _dismiss_transient_in_group(self, app_name: str) -> None:
        transient_ids = [n["id"] for n in self._groups.get(app_name, []) if not n["is_permanent"]]
        for nid in transient_ids:
            self.close_notification(nid, REASON_DISMISSED)

    # ------------------------------------------------------------------ helpers

    def _emit_dbus_signal(self, signal_name: str, params: GLib.Variant | None) -> None:
        if self._connection is None:
            return
        try:
            self._connection.emit_signal(
                None,
                NOTIFICATIONS_BUS_PATH,
                NOTIFICATIONS_BUS_NAME,
                signal_name,
                params,
            )
        except Exception as e:
            logger.warning(f"[Notifications] failed to emit signal {signal_name}: {e}")
