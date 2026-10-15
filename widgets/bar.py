#!/usr/bin/env -S uv run
import os
import sys
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.realpath(Path(__file__).parent))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from typing import Any

from fabric import Application
from gi.repository import Gdk, GLib

from fabric.widgets.wayland import WaylandWindow as Window

from fabric.widgets.centerbox import CenterBox
from fabric.widgets.box import Box
from fabric.widgets.separator import Separator


from modules.bar.active_window import ActiveWindowWidget
from modules.bar.brightness import BrightnessWidget
from modules.bar.clock import ClockWidget
from modules.bar.sound import Sound
from modules.bar.perf import PerfWidget
from modules.bar.systray import SystemTray
from modules.bar.weather import WeatherWidget
from modules.bar.workspaces import HyprlandWorkspacesTray
from modules.notification_center import NotificationCenter, NotificationPopup
from services.battery import Battery
from services.brightness import Brightness
from services.hyprland import HyprlandManager
from services.notifications import NotificationService
from services.system_tray import SystemTray as SystemTrayService
from services.weather import WeatherService

audio_widget: bool = True


try:
    from fabric.audio.service import Audio
except Exception:
    audio_widget = False
    Audio = None  # type: ignore[assignment]


def _gdk_index_for_hyprland_monitor(hypr_manager: HyprlandManager, monitor_id: int) -> int:
    """Resolve a Hyprland monitor ID to a GDK output index by matching (x, y) position."""
    mon = hypr_manager.monitors.get(monitor_id)
    if mon is not None:
        target_x, target_y = mon["x"], mon["y"]
        display = Gdk.Display.get_default()
        if display is None:
            return 0
        for i in range(display.get_n_monitors()):
            monitor = display.get_monitor(i)
            if monitor is None:
                continue
            geo = monitor.get_geometry()
            if geo.x == target_x and geo.y == target_y:
                return i
    return 0


class StatusBar(Window):
    def __init__(
        self,
        monitor_id: int,
        hyprland: HyprlandManager,
        battery_service: Battery,
        weather_service: WeatherService,
        brightness_service: Brightness,
        notif_service: NotificationService,
        systray_service: SystemTrayService,
        audio: Any = None,
    ):
        """
        - begin
            - left_panel_widget
            - screen_active_window
        - center
            - center_left
                - cpu
                - current_media
            - center_center
                - hprland_workspaces
            - center_right
                - date_time
                - tools
        - end
            - systray
            - right_panel
        """
        self.hyprland = hyprland
        gdk_index = _gdk_index_for_hyprland_monitor(self.hyprland, monitor_id)
        super().__init__(
            name="bar",
            layer="top",
            anchor="left top right",
            margin="0px 0px 0px 0px",
            exclusivity="auto",
            visible=False,
            monitor=gdk_index,
        )
        self.audio = audio
        self.clock = ClockWidget()

        self.weather_widget = WeatherWidget(weather_service, monitor=gdk_index)

        self.perf_widget = PerfWidget(battery_service, monitor=gdk_index)

        self.system_status = Box(name="system-status", spacing=4, orientation="h", children=[])
        self.active_window = ActiveWindowWidget(self.hyprland, monitor_id)
        self.workspaces = HyprlandWorkspacesTray(self.hyprland, two_rows=False, monitor_id=monitor_id)
        self.systray = SystemTray(systray_service)
        self.notif_center = NotificationCenter(notif_service, monitor=gdk_index)
        self.sound = Sound(self.audio, monitor=gdk_index) if self.audio is not None else None
        # self.media_player = MediaPlayer(self.audio)
        self.brightness = BrightnessWidget(brightness_service, monitor_id, monitor=gdk_index)

        self.left_box = Box(
            name="bar-left-box",
            children=[
                self.active_window,
                Box(children=[w for w in [self.sound, self.brightness] if w is not None], spacing=4),
            ],
            spacing=10,
        )
        self.center_box = CenterBox(
            name="bar-inner-box",
            start_children=self.weather_widget,
            center_children=self.workspaces,
            end_children=self.perf_widget,
            spacing=10,
        )
        self.children = CenterBox(
            name="bar-inner",
            start_children=self.left_box,
            center_children=self.center_box,
            end_children=Box(
                name="bar-end-box",
                orientation="h",
                spacing=6,
                style_classes=["top-widget"],
                children=[
                    self.notif_center,
                    Separator(orientation="v", name="end-sep"),
                    self.systray,
                ],
            ),
            h_align="fill",
            h_expand=True,
        )

        self.show_all()


if __name__ == "__main__":
    os.environ["XDG_DATA_DIRS"] = "/usr/local/share:/usr/share"

    def make_bar(monitor_id: int) -> StatusBar:
        return StatusBar(
            monitor_id=monitor_id,
            hyprland=hypr_manager,
            audio=shared_audio,
            battery_service=shared_battery,
            weather_service=shared_weather,
            brightness_service=shared_brightness,
            notif_service=shared_notif,
            systray_service=shared_systray,
        )

    _rebuild_pending: list[int | None] = [None]  # holds the GLib source id for the debounce timer

    def on_monitor_added(_, monitor_id: int) -> None:
        if monitor_id in bars:
            return

        name = hypr_manager.monitors[monitor_id].get("name", "?")
        print(f"[bar] adding bar for monitor id={monitor_id} name={name}")

        bar = make_bar(monitor_id)
        bars[monitor_id] = bar
        app.add_window(bar)


    def on_monitor_removed(_, monitor_id: int) -> None:
        bar = bars.pop(monitor_id, None)
        if bar is None:
            return

        print(f"[bar] removing bar for monitor id={monitor_id}")

        app.remove_window(bar)
        bar.close()

    hypr_manager = HyprlandManager()
    shared_audio = Audio() if Audio is not None else None
    shared_weather = WeatherService(city="Paris", fetch_interval_minutes=10, use_uscs=False)
    shared_battery = Battery()
    shared_brightness = Brightness(hypr_manager)
    shared_notif = NotificationService(hyprland=hypr_manager)
    shared_systray = SystemTrayService()
    shared_popup = NotificationPopup(shared_notif)

    hypr_manager.connect("monitor-added", on_monitor_added)
    hypr_manager.connect("monitor-removed", on_monitor_removed)

    bars = {mid: make_bar(mid) for mid in hypr_manager.monitors}
    app = Application("bars", *bars.values(), shared_popup)
    css_path = os.path.join(PROJECT_DIR, "styles/pure_black/style.css")
    app.set_stylesheet_from_file(css_path)
    app.run()
