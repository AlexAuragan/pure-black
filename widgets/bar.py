#!/usr/bin/env -S uv run
import os
import sys
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.realpath(Path(__file__).parent))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from fabric import Application


from fabric.widgets.wayland import WaylandWindow as Window

from fabric.widgets.centerbox import CenterBox
from fabric.widgets.box import Box


from modules.bar.active_window import ActiveWindowWidget
from modules.bar.brightness import BrightnessWidget
from modules.bar.clock import ClockWidget
from modules.bar.media_player import MediaPlayer
from modules.bar.sound import Sound
from modules.bar.perf import PerfWidget
from modules.bar.systray import SystemTray
from modules.bar.weather import WeatherWidget
from modules.bar.workspaces import HyprlandWorkspacesTray
from services.brightness import Brightness
from services.hyprland import HyprlandManager
from services.weather import WeatherService

AUDIO_WIDGET = True


if AUDIO_WIDGET:
    try:
        from fabric.audio.service import Audio
    except Exception as e:
        AUDIO_WIDGET = False



class StatusBar(Window):
    def __init__(
        self, monitor=1
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
        super().__init__(
            name="bar",
            layer="top",
            anchor="left top right",
            margin="0px 0px 0px 0px",
            exclusivity="auto",
            visible=False,
            monitor=monitor,
        )
        self.audio = Audio()
        self.clock = ClockWidget()

        self.weather_service = WeatherService(city="Paris", fetch_interval_minutes=10, use_uscs=False)
        self.weather_widget = WeatherWidget(self.weather_service)

        # self.active_window = ActiveWindowWidget(HyprlandManager())
        self.perf_widget = PerfWidget()


        self.system_status = Box(
            name="system-status",
            spacing=4,
            orientation="h",
            children=[]
        )
        self.hyprland = HyprlandManager()
        self.active_window = ActiveWindowWidget(self.hyprland, self.monitor)
        self.workspaces = HyprlandWorkspacesTray(self.hyprland, two_rows=False, monitor_id=monitor)
        self.systray = SystemTray()
        self.sound = Sound(self.audio)
        # self.media_player = MediaPlayer(self.audio)
        print("monitor", self.monitor)
        self.brightness = BrightnessWidget(Brightness(self.hyprland), self.monitor)

        self.left_box = Box(
            name="bar-left-box",
            children=[self.active_window, Box(children=[self.sound, self.brightness], spacing=4)],
            spacing=10
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
            h_align="fill", # / fill / baseline / start
            h_expand=True # / False
        )

        self.show_all()


if __name__ == "__main__":
    os.environ["XDG_DATA_DIRS"] = "/usr/local/share:/usr/share"


    def on_monitor_added(manager, monitor_id):
        print(monitor_id)
        new_bar = StatusBar(monitor=monitor_id)
        app.add_window(new_bar)


    hypr_manager = HyprlandManager()
    hypr_manager.connect("monitor-added", on_monitor_added)

    monitors = hypr_manager.monitors
    monitor_ids = monitors.keys() if monitors else [0]
    bars = [StatusBar(monitor=m_id) for m_id in monitor_ids]
    app = Application("bars", *bars)
    css_path = os.path.join(PROJECT_DIR, "styles/pure_black/style.css")
    app.set_stylesheet_from_file(css_path)
    app.run()