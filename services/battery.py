import threading
from typing import Any

import psutil
from fabric.core.service import Property, Service, Signal
from fabric.utils.helpers import idle_add
from gi.repository import Gio, GLib
from loguru import logger

NOTIFICATIONS_BUS_NAME = "org.freedesktop.Notifications"
NOTIFICATIONS_BUS_PATH = "/org/freedesktop/Notifications"
NOTIFICATIONS_IFACE = "org.freedesktop.Notifications"

# org.freedesktop.Notifications.Notify:
# (app_name: s, replaces_id: u, app_icon: s, summary: s, body: s,
#  actions: as, hints: a{sv}, expire_timeout: i) -> u
_NOTIFY_SIGNATURE = "(susssasa{sv}i)"

# threshold -> (summary, urgency)
_LOW_BATTERY_ALERTS: dict[int, tuple[str, int]] = {
    20: ("Battery low", 1),
    10: ("Battery critically low", 2),
    5: ("Battery almost empty", 2),
}


class Battery(Service[Any, Any]):
    """
    Shared battery service.

    - reports whether a battery exists at all (desktops have none)
    - reports the current charge level and charging state
    - fires a desktop notification as the battery crosses each low threshold
    """

    @Signal
    def changed(self) -> None: ...

    def __init__(
        self,
        notify_thresholds: tuple[int, ...] = (20, 10, 5),
        poll_interval: float = 5.0,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._poll_interval = poll_interval
        self._thresholds = tuple(sorted(notify_thresholds, reverse=True))
        self._fired: set[int] = set()

        self._present = False
        self._percent: float | None = None
        self._charging = False

        self._stop = threading.Event()

        # first read is synchronous so `present` is already valid right after construction
        self._apply(self._read())
        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ------------------------------------------------------------------ props
    @Property(bool, "readable", default_value=False)
    def present(self) -> bool:
        "whether a battery exists (False on desktops)"
        return self._present

    @Property(float, "readable", default_value=0.0)
    def percent(self) -> float:
        "charge percentage (0.0 when there is no battery)"
        return self._percent if self._percent is not None else 0.0

    @Property(bool, "readable", default_value=False)
    def charging(self) -> bool:
        "whether the battery is currently plugged in / charging"
        return self._charging

    # ------------------------------------------------------------------ api
    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ polling
    @staticmethod
    def _read() -> Any | None:
        try:
            return psutil.sensors_battery()
        except Exception as e:
            logger.warning(f"[Battery] could not read battery state: {e}")
            return None

    def _poll_loop(self) -> None:
        # `wait` returns True once the stop event is set
        while not self._stop.wait(self._poll_interval):
            idle_add(self._apply, self._read())

    def _apply(self, snapshot: Any | None) -> None:
        present = snapshot is not None
        try:
            percent = float(snapshot.percent) if present else None
        except (TypeError, ValueError):
            percent = None
        charging = bool(snapshot.power_plugged) if present else False

        changed = (present, percent, charging) != (self._present, self._percent, self._charging)
        self._present = present
        self._percent = percent
        self._charging = charging

        self._maybe_notify()

        if changed:
            self.notify("present", "percent", "charging")
            self.changed()

    # ------------------------------------------------------------------ alerts
    def _maybe_notify(self) -> None:
        if not self._present or self._percent is None:
            return
        if self._charging:
            # plugged in -> re-arm every threshold for the next discharge
            self._fired.clear()
            return

        percent = self._percent
        crossed = [t for t in self._thresholds if percent <= t and t not in self._fired]
        for t in self._thresholds:
            if percent > t:
                self._fired.discard(t)

        if not crossed:
            return
        self._fired.update(crossed)
        # if several thresholds are crossed at once, only warn about the most urgent
        self._send_low_battery(min(crossed), percent)

    def _send_low_battery(self, threshold: int, percent: float) -> None:
        summary, urgency = _LOW_BATTERY_ALERTS.get(threshold, ("Battery low", 1))
        self._send_notification(summary, f"{percent:.0f}% remaining", urgency=urgency, value=percent)

    @staticmethod
    def _send_notification(summary: str, body: str, urgency: int = 1, value: float | None = None) -> None:
        hints: dict[str, GLib.Variant] = {"urgency": GLib.Variant("y", urgency)}
        if value is not None:
            hints["value"] = GLib.Variant("i", int(value))
        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.call_sync(
                NOTIFICATIONS_BUS_NAME,
                NOTIFICATIONS_BUS_PATH,
                NOTIFICATIONS_IFACE,
                "Notify",
                GLib.Variant(
                    _NOTIFY_SIGNATURE,
                    ("FabricRice", 0, "", summary, body, [], hints, -1),
                ),
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
        except Exception as e:
            logger.warning(f"[Battery] failed to send notification: {e}")
