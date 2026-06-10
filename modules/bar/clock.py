import datetime
from typing import Any

from fabric.widgets.box import Box
from fabric.widgets.label import Label
from gi.repository import GLib


class ClockWidget(Box):
    def __init__(self, **kwargs: Any):
        self.label = Label()
        super().__init__(name="clock-widget", orientation="h", spacing=6, children=[self.label])
        self._tick()
        GLib.timeout_add(500, self._tick)
        self.set_has_tooltip(True)

    def _tick(self) -> bool:
        now = datetime.datetime.now()
        self.label.set_label(now.strftime("%H:%M:%S"))
        self.set_tooltip_markup(now.strftime("%A %d %B %Y"))
        return True


class WeatherIcon(Label):
    def __init__(self, icon_name: str):
        super().__init__(
            label=icon_name,
            name="weather-icon",
            style="""
    font-family: "Material Symbols Rounded";
    font-size: 16px;
""",
        )
