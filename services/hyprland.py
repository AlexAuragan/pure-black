import json
from typing import TYPE_CHECKING, Any, TypedDict

from fabric import Signal
from fabric.core.service import Property, Service
from fabric.hyprland import Hyprland, HyprlandReply
from fabric.utils.helpers import idle_add
from gi.repository.GdkPixbuf import Pixbuf

from utils.find_icon import guess_icon_path_from_window_class


def _decode_json(reply: HyprlandReply) -> Any | None:
    raw: bytes = reply.reply
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


class Workspace(TypedDict):
    id: str | int
    name: str
    monitor: str
    monitor_id: int
    windows: int
    has_full_screen: bool
    last_window: str
    last_window_title: str
    is_persistent: bool


class Monitor(TypedDict):
    id: int
    name: str
    description: str
    make: str
    model: str
    serial: str
    width: int
    height: int
    physical_width: int
    physical_height: int
    refresh_rate: float | int
    x: int
    y: int
    active_workspace_id: int
    active_workspace_name: str
    special_workspace_id: int
    special_workspace_name: str
    reserved: list[int]
    scale: float | int
    transform: int
    focused: bool
    dpms_status: bool
    vrr: bool
    solitary: str
    solitary_blocked_by: list[str]
    actively_tearing: bool
    tearing_blocked_by: list[str]
    direct_scanout_to: str
    direct_scanout_blocked_by: list[str]
    disabled: bool
    current_format: str
    mirror_of: None | str
    available_modes: list[str]
    color_management_preset: str
    sdr_brightness: float
    sdr_saturation: float
    sdr_min_luminance: float | int
    sdr_max_luminance: float | int


class ActiveWindow(TypedDict):
    address: str
    mapped: bool
    hidden: bool
    at: list[int]
    size: list[int]
    workspace_id: int
    workspace_name: str
    floating: bool
    monitor: int
    class_: str
    title: str
    initialClass: str
    initialTitle: str
    pid: int
    xwayland: bool
    pinned: bool
    fullscreen: int
    fullscreenClient: int
    grouped: list[str]
    tags: list[str]
    swallowing: str
    focusHistoryID: int
    inhibitingIdle: bool
    xdgTag: str
    xdgDescription: str


class Client(TypedDict):
    address: str
    mapped: bool
    hidden: bool
    at: tuple[int, int]
    size: tuple[int, int]
    workspace_id: int
    workspace_name: str
    floating: bool
    monitor: int
    class_: str
    title: str
    initial_class: str
    initial_title: str
    pid: int
    xwayland: bool
    pinned: bool
    fullscreen: int | bool
    fullscreen_client: int | bool
    grouped: list[str]
    tags: list[str]
    swallowing: str
    focus_history_id: int
    inhibiting_idle: bool
    xdg_tag: str
    xdg_description: str


class WorkspaceIcon(TypedDict):
    workspace_id: int
    last_client_address: str | None
    has_clients: bool
    icon_pixbuf: Pixbuf | None


class HyprlandManager(Service[Any, Any]):
    """
    Cache layer on top of the official Hyprland transport.

    - subscribes to Hyprland 'event::<name>' signals
    - refreshes cached state via socket commands (j/<endpoint>)
    - exposes bindable properties similar to your previous manager
    """

    if TYPE_CHECKING:

        @property
        def workspaces(self) -> dict[int, Workspace]:
            return self._workspaces

        @property
        def monitors(self) -> dict[int, Monitor]:
            return self._monitors

        @property
        def active_windows(self) -> dict[int, ActiveWindow | None]:
            return self._active_windows

        @property
        def clients(self) -> dict[str, Client]:
            return self._clients

        @property
        def workspace_icons(self) -> dict[int, WorkspaceIcon]:
            return self._workspace_icons

    else:

        @Property(object, "readable", "workspaces", default_value=None)
        def workspaces(self):
            return self._workspaces

        @Property(object, "readable", "monitors", default_value=None)
        def monitors(self):
            return self._monitors

        @Property(object, "readable", "active_windows", default_value=None)
        def active_windows(self):
            return self._active_windows

        @Property(object, "readable", "clients", default_value=None)
        def clients(self):
            return self._clients

        @Property(object, "readable", "workspace_icons", default_value=None)
        def workspace_icons(self):
            return self._workspace_icons

    @Signal(name="workspace-icons-changed")
    def workspace_icons_changed(self, workspace_id: int) -> None: ...

    @Signal(name="monitor-added")
    def monitor_added(self, monitor_id: int) -> None: ...

    @Signal(name="monitor-removed")
    def monitor_removed(self, monitor_id: int) -> None: ...

    def __init__(self, hypr: Hyprland | None = None, **kwargs: Any):
        super().__init__(**kwargs)

        # transport
        self.hypr = hypr or Hyprland(commands_only=False)

        # cached state
        self._workspaces: dict[int, Workspace] = {}
        self._monitors: dict[int, Monitor] = {}
        self._active_windows: dict[int, ActiveWindow | None] = {}
        self._clients: dict[str, Client] = {}
        self._workspace_icons: dict[int, WorkspaceIcon] = {}
        self._addr_to_class: dict[str, str] = {}
        self._class_to_icon: dict[str, Pixbuf | None] = {}
        self._workspace_last_client: dict[int, str | None] = {}

        self._pending_workspaces = False
        self._pending_monitors = False
        self._pending_activewindow = False
        self._pending_clients = False
        self._pending_workspace_icons = False

        self._connect_events()

        # initial fill
        self.refresh_all()

    def close(self) -> None:
        pass

    def refresh_all(self) -> None:
        self._apply_workspaces(self.hypr.send_command("j/workspaces"))
        self._apply_monitors(self.hypr.send_command("j/monitors"))
        self._apply_clients(self.hypr.send_command("j/clients"))
        self._apply_activewindow(self.hypr.send_command("j/activewindow"))
        self._schedule_workspaces_refresh()
        self._schedule_monitors_refresh()
        self._schedule_activewindow_refresh()
        self._schedule_clients_refresh()

    def _connect_events(self) -> None:
        # 1. Topology changes (workspaces/monitors)
        for name in (
            "workspace",
            "createworkspace",
            "destroyworkspace",
            "focusedmon",
        ):
            self.hypr.connect(f"event::{name}", self._on_topology_event)

        # 2. Monitor plug/unplug
        for name in ("monitoradded", "monitorremoved", "monitoraddedv2"):
            self.hypr.connect(f"event::{name}", self._on_topology_event)

        # 3. Active window + presentation state
        for name in (
            "activewindow",
            "activewindowv2",
            "windowtitle",
            "windowtitlev2",
            "fullscreen",
            "openwindow",
            "closewindow",
            "movewindow",
            "movewindowv2",
        ):
            self.hypr.connect(f"event::{name}", self._on_activewindow_event)

        # 4. Client list changes
        for name in (
            "changefloatingmode",
            # Note: open/close/move are already covered for activewindow,
            # but we also need them to trigger client list refreshes.
            "openwindow",
            "closewindow",
            "movewindow",
            "movewindowv2",
        ):
            self.hypr.connect(f"event::{name}", self._on_clients_event)

    def _on_topology_event(self, *_args: Any) -> None:
        self._schedule_workspaces_refresh()
        self._schedule_monitors_refresh()

    def _on_activewindow_event(self, *_args: Any) -> None:
        self._schedule_activewindow_refresh()

    def _on_clients_event(self, *_args: Any) -> None:
        self._schedule_clients_refresh()
        self._schedule_workspaces_refresh()

    def _schedule_workspaces_refresh(self) -> None:
        if self._pending_workspaces:
            return
        self._pending_workspaces = True
        idle_add(self._refresh_workspaces)

    def _schedule_monitors_refresh(self) -> None:
        if self._pending_monitors:
            return
        self._pending_monitors = True
        idle_add(self._refresh_monitors)

    def _schedule_activewindow_refresh(self) -> None:
        if self._pending_activewindow:
            return
        self._pending_activewindow = True
        idle_add(self._refresh_activewindow)

    def _schedule_clients_refresh(self) -> None:
        if self._pending_clients:
            return
        self._pending_clients = True
        idle_add(self._refresh_clients)

    def _schedule_workspace_icons_refresh(self) -> None:
        if self._pending_workspace_icons:
            return
        self._pending_workspace_icons = True
        idle_add(self._refresh_workspace_icons)

    def _refresh_workspace_icons(self) -> None:
        self._pending_workspace_icons = False
        self._recompute_workspace_icons()

    def _refresh_workspaces(self) -> None:
        self._pending_workspaces = False
        self.hypr.send_command_async("j/workspaces", self._apply_workspaces)

    def _refresh_monitors(self) -> None:
        self._pending_monitors = False
        self.hypr.send_command_async("j/monitors", self._apply_monitors)

    def _refresh_activewindow(self) -> None:
        self._pending_activewindow = False
        self.hypr.send_command_async("j/activewindow", self._apply_activewindow)

    def _refresh_clients(self) -> None:
        self._pending_clients = False
        self.hypr.send_command_async("j/clients", self._apply_clients)

    def _icon_for_class(self, class_: str) -> Pixbuf | None:
        if not class_:
            return None
        if class_ not in self._class_to_icon:
            path = guess_icon_path_from_window_class(class_)
            if path:
                pb = Pixbuf.new_from_file_at_scale(
                    filename=path,
                    width=16,
                    height=16,
                    preserve_aspect_ratio=True,
                )
            else:
                pb = None
            self._class_to_icon[class_] = pb
        return self._class_to_icon[class_]

    def _recompute_workspace_icons(self) -> None:
        clients = self._clients

        # workspace -> [addresses]
        ws_clients: dict[int, list[str]] = {}
        for addr, c in clients.items():
            ws_id = int(c["workspace_id"])
            ws_clients.setdefault(ws_id, []).append(addr)

        new_icons: dict[int, WorkspaceIcon] = {}

        # include all known workspaces (and also any ws_id seen in clients)
        ws_ids = set(self._workspaces.keys()) | set(ws_clients.keys())

        for ws_id in ws_ids:
            addrs = ws_clients.get(ws_id, [])
            has_clients = bool(addrs)

            # pick last client address:
            last_addr = self._workspace_last_client.get(ws_id, "")

            # if last addr is missing, try Hyprland workspace last_window (if present and still alive)
            if last_addr and last_addr not in clients:
                last_addr = ""

            if not last_addr:
                ws = self._workspaces.get(ws_id)
                if ws:
                    candidate = ws.get("last_window", "") or ""
                    if candidate in clients:
                        last_addr = candidate

            # fallback: deterministic first client
            if not last_addr and addrs:
                last_addr = sorted(addrs)[0]

            icon_pixbuf: Pixbuf | None = None
            if last_addr:
                class_ = self._addr_to_class.get(last_addr, "")
                icon_pixbuf = self._icon_for_class(class_)

            wi: WorkspaceIcon = {
                "workspace_id": ws_id,
                "last_client_address": last_addr,
                "icon_pixbuf": icon_pixbuf,
                "has_clients": has_clients,
            }
            new_icons[ws_id] = wi

        updated = []
        for key in set(new_icons.keys()) | set(self._workspace_icons.keys()):
            if new_icons.get(key) != self._workspace_icons.get(key):
                updated.append(key)
        if updated:
            self._workspace_icons = new_icons
            self.notify("workspace_icons")
            for workspace_id in updated:
                self.emit("workspace-icons-changed", workspace_id)

    def _apply_workspaces(self, reply: HyprlandReply) -> None:
        raw = _decode_json(reply)
        if not isinstance(raw, list):
            return

        new: dict[int, Workspace] = {}
        for ws in raw:
            if not isinstance(ws, dict):
                continue
            ws_id = int(ws.get("id", 0))

            new[ws_id] = {
                "id": ws_id,
                "name": ws.get("name", ""),
                "monitor": ws.get("monitor", ""),
                "monitor_id": ws.get("monitorID", 0),
                "windows": ws.get("windows", 0),
                "has_full_screen": ws.get("hasfullscreen", False),
                "last_window": ws.get("lastwindow", ""),
                "last_window_title": ws.get("lastwindowtitle", ""),
                "is_persistent": ws.get("ispersistent", False),
            }

        if new != self._workspaces:
            self._workspaces = new
            self.notify("workspaces")
            self._schedule_workspace_icons_refresh()

    def _apply_monitors(self, reply: HyprlandReply) -> None:
        raw = _decode_json(reply)
        if not isinstance(raw, list):
            return
        old_ids = set(self._monitors.keys())
        new: dict[int, Monitor] = {}
        for mon in raw:
            if not isinstance(mon, dict):
                continue
            mid = int(mon.get("id", 0))
            special_ws = mon.get("specialWorkspace") or {}
            active_ws = mon.get("activeWorkspace") or {}
            new_mon: Monitor = {
                "id": mid,
                "name": mon["name"],
                "description": mon["description"],
                "make": mon["make"],
                "model": mon["model"],
                "serial": mon["serial"],
                "width": mon["width"],
                "height": mon["height"],
                "physical_width": mon["physicalWidth"],
                "physical_height": mon["physicalHeight"],
                "refresh_rate": mon["refreshRate"],
                "x": mon["x"],
                "y": mon["y"],
                "active_workspace_id": int(active_ws.get("id", 0) or 0),
                "active_workspace_name": str(active_ws.get("name", "")),
                "special_workspace_id": int(special_ws.get("id", 0) or 0),
                "special_workspace_name": str(special_ws.get("name", "")),
                "reserved": mon["reserved"],
                "scale": mon["scale"],
                "transform": mon["transform"],
                "focused": mon["focused"],
                "dpms_status": mon["dpmsStatus"],
                "vrr": mon["vrr"],
                "solitary": mon["solitary"],
                "solitary_blocked_by": mon["solitaryBlockedBy"],
                "actively_tearing": mon["activelyTearing"],
                "tearing_blocked_by": mon["tearingBlockedBy"],
                "direct_scanout_to": mon["directScanoutTo"],
                "direct_scanout_blocked_by": mon["directScanoutBlockedBy"],
                "disabled": mon["disabled"],
                "current_format": mon["currentFormat"],
                "mirror_of": mon["mirrorOf"],
                "available_modes": mon["availableModes"],
                "color_management_preset": mon["colorManagementPreset"],
                "sdr_brightness": mon["sdrBrightness"],
                "sdr_saturation": mon["sdrSaturation"],
                "sdr_min_luminance": mon["sdrMinLuminance"],
                "sdr_max_luminance": mon["sdrMaxLuminance"],
            }
            new[mid] = new_mon

        if new != self._monitors:
            new_ids = set(new.keys())
            added_ids = new_ids - old_ids
            removed_ids = old_ids - new_ids
            self._monitors = new
            self.notify("monitors")
            for monitor_id in sorted(added_ids):
                self.emit("monitor-added", monitor_id)

            for monitor_id in sorted(removed_ids):
                self.emit("monitor-removed", monitor_id)

    def _apply_activewindow(self, reply: HyprlandReply) -> None:
        raw = _decode_json(reply)
        if not isinstance(raw, dict) or not raw:
            changed = False
            for k in list(self._active_windows.keys()):
                if self._active_windows.get(k) is not None:
                    self._active_windows[k] = None
                    changed = True
            if changed:
                self.notify("active_windows")
                self._schedule_workspace_icons_refresh()
            return

        mon = raw.get("monitor", 0)
        mon_id = int(mon)

        ws = raw.get("workspace") if isinstance(raw.get("workspace"), dict) else {}
        new_window: ActiveWindow | None
        if ws:
            new_window = {
                "address": raw.get("address", ""),
                "mapped": bool(raw.get("mapped", False)),
                "hidden": bool(raw.get("hidden", False)),
                "at": list(raw.get("at", [0, 0])),
                "size": list(raw.get("size", [0, 0])),
                "workspace_id": int(ws.get("id", 0)),
                "workspace_name": str(ws.get("name", "")),
                "floating": bool(raw.get("floating", False)),
                "monitor": int(raw.get("monitor", 0)),
                "class_": str(raw.get("class", "")),
                "title": str(raw.get("title", "")),
                "initialClass": str(raw.get("initialClass", "")),
                "initialTitle": str(raw.get("initialTitle", "")),
                "pid": int(raw.get("pid", 0)),
                "xwayland": bool(raw.get("xwayland", False)),
                "pinned": bool(raw.get("pinned", False)),
                "fullscreen": int(raw.get("fullscreen", 0)),
                "fullscreenClient": int(raw.get("fullscreenClient", 0)),
                "grouped": list(raw.get("grouped", [])),
                "tags": list(raw.get("tags", [])),
                "swallowing": str(raw.get("swallowing", "")),
                "focusHistoryID": int(raw.get("focusHistoryID", 0)),
                "inhibitingIdle": bool(raw.get("inhibitingIdle", False)),
                "xdgTag": str(raw.get("xdgTag", "")),
                "xdgDescription": str(raw.get("xdgDescription", "")),
            }
        else:
            new_window = None

        prev = self._active_windows.get(mon_id)
        if prev != new_window:
            self._active_windows[mon_id] = new_window
            self.notify("active_windows")

            if new_window is not None:
                ws_id = int(new_window["workspace_id"])
                addr = new_window["address"]
                if addr:
                    self._workspace_last_client[ws_id] = addr
                    self._schedule_workspace_icons_refresh()

    def _apply_clients(self, reply: HyprlandReply) -> None:
        raw = _decode_json(reply)
        if not isinstance(raw, list):
            return

        new: dict[str, Client] = {}
        for client in raw:
            if not isinstance(client, dict):
                continue
            addr = client.get("address")
            if not isinstance(addr, str) or not addr:
                continue
            ws = (client.get("workspace") if isinstance(client.get("workspace"), dict) else {}) or {}
            at = client.get("at") or [0, 0]
            size = client.get("size") or [0, 0]
            new_client: Client = {
                "address": client["address"],
                "mapped": client["mapped"],
                "hidden": client["hidden"],
                "at": (int(at[0]), int(at[1])),
                "size": (int(size[0]), int(size[1])),
                "workspace_id": ws["id"],
                "workspace_name": ws["name"],
                "floating": client["floating"],
                "monitor": client["monitor"],
                "class_": client["class"],
                "title": client["title"],
                "initial_class": client["initialClass"],
                "initial_title": client["initialTitle"],
                "pid": client["pid"],
                "xwayland": client["xwayland"],
                "pinned": client["pinned"],
                "fullscreen": client["fullscreen"],
                "fullscreen_client": client["fullscreenClient"],
                "grouped": client["grouped"],
                "tags": client["tags"],
                "swallowing": client["swallowing"],
                "focus_history_id": client["focusHistoryID"],
                "inhibiting_idle": client["inhibitingIdle"],
                "xdg_tag": client["xdgTag"],
                "xdg_description": client["xdgDescription"],
            }

            new[addr] = new_client

        if new != self._clients:
            self._clients = new
            self.notify("clients")

            # rebuild addr -> class_
            self._addr_to_class = {}
            for addr, c in self._clients.items():
                self._addr_to_class[addr] = c["class_"]

            # repair last-client pointers that now point to missing addresses
            for ws_id, addr in list(self._workspace_last_client.items()):
                if addr and addr not in self._clients:
                    del self._workspace_last_client[ws_id]

            self._schedule_workspace_icons_refresh()

    def focus_workspace_current_monitor(self, workspace_id: int) -> None:
        self.hypr.send_command_async(
            f'/dispatch hl.dsp.focus({{ workspace = "{workspace_id}" }})',
            lambda *_: None,
        )
