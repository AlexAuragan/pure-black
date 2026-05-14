#!/usr/bin/env -S uv run
import os
import sys
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.realpath(Path(__file__).parent))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from fabric import Application
from gi.repository import Gdk, GLib

from fabric.widgets.wayland import WaylandWindow as Window

from fabric.widgets.centerbox import CenterBox
from fabric.widgets.box import Box


from modules.bar.active_window import ActiveWindowWidget
from modules.bar.brightness import BrightnessWidget
from modules.bar.clock import ClockWidget
from modules.bar.sound import Sound
from modules.bar.perf import PerfWidget
from modules.bar.systray import SystemTray
from modules.bar.weather import WeatherWidget
from modules.bar.workspaces import HyprlandWorkspacesTray
from services.brightness import Brightness
from services.hyprland import HyprlandManager
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
        for i in range(display.get_n_monitors()):
            geo = display.get_monitor(i).get_geometry()
            if geo.x == target_x and geo.y == target_y:
                return i
    return 0


class StatusBar(Window):
    def __init__(
        self,
        monitor_id: int,
        hyprland: HyprlandManager | None = None,
        audio=None,
        weather_service: WeatherService | None = None,
        brightness_service: Brightness | None = None,
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
        self.hyprland = hyprland or HyprlandManager()
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

        _weather = weather_service or WeatherService(city="Paris", fetch_interval_minutes=10, use_uscs=False)
        self.weather_widget = WeatherWidget(_weather)

        # self.active_window = ActiveWindowWidget(HyprlandManager())
        self.perf_widget = PerfWidget()

        self.system_status = Box(name="system-status", spacing=4, orientation="h", children=[])
        self.active_window = ActiveWindowWidget(self.hyprland, monitor_id)
        self.workspaces = HyprlandWorkspacesTray(self.hyprland, two_rows=False, monitor_id=monitor_id)
        self.systray = SystemTray()
        self.sound = Sound(self.audio) if self.audio is not None else None
        # self.media_player = MediaPlayer(self.audio)
        _brightness = brightness_service or Brightness(self.hyprland)
        self.brightness = BrightnessWidget(_brightness, monitor_id)

        self.left_box = Box(
            name="bar-left-box",
            children=[
                self.active_window,
                Box(children=[self.sound, self.brightness], spacing=4),
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
            end_children=self.systray,
            h_align="fill",  # / fill / baseline / start
            h_expand=True,  # / False
        )

        self.show_all()


if __name__ == "__main__":
    os.environ["XDG_DATA_DIRS"] = "/usr/local/share:/usr/share"

    def make_bar(monitor_id):
        return StatusBar(
            monitor_id=monitor_id,
            hyprland=hypr_manager,
            audio=shared_audio,
            weather_service=shared_weather,
            brightness_service=shared_brightness,
        )

    _rebuild_pending = [None]  # holds the GLib source id for the debounce timer

    def rebuild_bars(*_):
        if _rebuild_pending[0] is not None:
            GLib.source_remove(_rebuild_pending[0])
        _rebuild_pending[0] = GLib.timeout_add(200, _do_rebuild)

    def _do_rebuild():
        _rebuild_pending[0] = None
        for bar in list(bars.values()):
            bar.close()
        bars.clear()
        monitor_ids = list(hypr_manager.monitors.keys())

        def create_next(idx):
            if idx >= len(monitor_ids):
                return False
            mid = monitor_ids[idx]
            name = hypr_manager.monitors[mid].get("name", "?")
            print(f"[bar] rebuilding bar for monitor id={mid} name={name}")
            new_bar = make_bar(mid)
            bars[mid] = new_bar
            app.add_window(new_bar)
            GLib.idle_add(create_next, idx + 1)
            return False

        GLib.idle_add(create_next, 0)
        return False

    hypr_manager = HyprlandManager()
    shared_audio = Audio() if Audio is not None else None
    shared_weather = WeatherService(city="Paris", fetch_interval_minutes=10, use_uscs=False)
    shared_brightness = Brightness(hypr_manager)

    hypr_manager.connect("monitor-added", rebuild_bars)
    hypr_manager.connect("monitor-removed", rebuild_bars)

    bars = {mid: make_bar(mid) for mid in hypr_manager.monitors}
    app = Application("bars", *bars.values())
    css_path = os.path.join(PROJECT_DIR, "styles/pure_black/style.css")
    app.set_stylesheet_from_file(css_path)
    app.run()
