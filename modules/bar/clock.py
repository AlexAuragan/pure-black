import subprocess
from typing import override

from fabric import Fabricator
from fabric.widgets.box import Box
from fabric.widgets.label import Label


class ClockLabel(Label):
    @override
    def set_label(self, string) -> None:
        # Tue Feb  3 12:10:01 AM CET 2026
        wday, month, mday, hour, am, tz, y = string.split()
        h, m, s = hour.split(":")
        h, m, s = int(h), int(m), int(s)
        ampm = am.lower()
        if ampm == "am":
            if h == 12:
                h = 0
        elif ampm == "pm":
            if h != 12:
                h += 12
        s = f"{s}" if s >= 10 else f"0{s}"
        m = f"{m}" if m >= 10 else f"0{m}"
        h = f"{h}" if h >= 10 else f"0{h}"
        super().set_label(f"{h}:{m}:{s}")


class ClockWidget(Box):
    def __init__(self, **kwargs):

        self.label = ClockLabel()
        self.fabricator = Fabricator(
            interval=500,
            poll_from="date",
            on_changed=lambda f, v: self.label.set_label(v)
        ),

        super().__init__(
            name="clock-widget",
            orientation="h",
            spacing=6,
            children=[self.label]
        )

        self.build(lambda x: self.fabricator)
        self.set_has_tooltip(True)
        self.set_tooltip_markup(self._tooltip_markup())



    def _tooltip_markup(self,) -> str:
        # Keep it readable and stable even if some fields are missing
        date = subprocess.run("date", capture_output=True)
        date = date.stdout.decode("utf-8").strip()
        wday, month, mday, hour, am, tz, y = date.split()

        return f"{wday} {mday} {month} {y}"



class WeatherIcon(Label):
    def __init__(self, icon_name: str):
        super().__init__(
            label=icon_name,
            name="weather-icon",
            style="""
    font-family: "Material Symbols Rounded";
    font-size: 16px;
"""
        )
