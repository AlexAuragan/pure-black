import os
import subprocess
from datetime import datetime
from typing import Any
from pathlib import Path
from urllib.parse import quote_plus

from fabric.widgets.eventbox import EventBox
from fabric.widgets.box import Box
from fabric.widgets.label import Label
from fabric.widgets.separator import Separator
from components import Svg
from gi.repository import Gdk, Gtk

from components.popup_widget import PopupWidget, PopupWindow
from services.weather import WeatherService, WeatherServiceData

WEATHER_CODE_TO_ICON_NAME = {
    "113": "clear_day",
    "116": "partly_cloudy_day",
    "119": "cloud",
    "122": "cloud",
    "143": "foggy",
    "176": "rainy",
    "179": "rainy",
    "182": "rainy",
    "185": "rainy",
    "200": "thunderstorm",
    "227": "cloudy_snowing",
    "230": "snowing_heavy",
    "248": "foggy",
    "260": "foggy",
    "263": "rainy",
    "266": "rainy",
    "281": "rainy",
    "284": "rainy",
    "293": "rainy",
    "296": "rainy",
    "299": "rainy",
    "302": "weather_hail",
    "305": "rainy",
    "308": "weather_hail",
    "311": "rainy",
    "314": "rainy",
    "317": "rainy",
    "320": "cloudy_snowing",
    "323": "cloudy_snowing",
    "326": "cloudy_snowing",
    "329": "snowing_heavy",
    "332": "snowing_heavy",
    "335": "snowing",
    "338": "snowing_heavy",
    "350": "rainy",
    "353": "rainy",
    "356": "rainy",
    "359": "weather_hail",
    "362": "rainy",
    "365": "rainy",
    "368": "cloudy_snowing",
    "371": "snowing",
    "374": "rainy",
    "377": "rainy",
    "386": "thunderstorm",
    "389": "thunderstorm",
    "392": "thunderstorm",
    "395": "snowing",
}
ICON_NAME_TO_TAG = {
    "clear_day": "Clear",
    "partly_cloudy_day": "Partly cloudy",
    "cloud": "Cloudy",
    "foggy": "Fog",
    "rainy": "Rain",
    "thunderstorm": "Storm",
    "cloudy_snowing": "Snow",
    "snowing": "Snow",
    "snowing_heavy": "Heavy snow",
    "weather_hail": "Hail",
}


class WeatherPopupView(Box):
    def __init__(self, weather: WeatherService, **kwargs: Any):
        super().__init__(
            name="weather-popup",
            orientation="v",
            spacing=10,
            **kwargs,
        )
        self.weather = weather
        # --- Title ---
        self.title = Label(name="weather-popup-title", label="Today")
        self.add(self.title)

        # --- TODAY (3 columns) ---
        self.today_row = Box(orientation="h", spacing=12)

        # Left: sunrise + wind
        self.left_col = Box(orientation="v", spacing=6)
        self.sunrise = Label(name="weather-popup-sunrise", label="↑ --")
        self.wind = Label(name="weather-popup-wind", label="--")
        self.left_col.add(self.sunrise)
        self.wind_icon = Svg(svg_file=icon_file_from_name("wind"), size=14)
        self.wind_icon.add_style_class("weather-icon")
        self.left_col.add(
            Box(
                children=[self.wind_icon, self.wind],
                orientation="horizontal",
                spacing=2,
            )
        )

        # Center: big icon + label (keep label for today)
        self.center_col = Box(orientation="v", spacing=6, h_expand=True)
        self.today_icon = Svg(svg_file=icon_file_from_name("cloud"), size=34)
        self.today_icon.add_style_class("weather-icon")
        self.today_text = Label(name="weather-popup-now", label="--")  # e.g. "Partly cloudy · 9℃"
        self.center_col.add(self.today_icon)
        self.center_col.add(self.today_text)

        # Right: sunset + precip
        self.right_col = Box(orientation="v", spacing=6)
        self.sunset = Label(name="weather-popup-sunset", label="↓ --")
        self.precip = Label(name="weather-popup-precip", label="--")
        self.right_col.add(self.sunset)
        self.water_drop_icon = Svg(svg_file=icon_file_from_name("water_drop"), size=14)
        self.water_drop_icon.add_style_class("weather-icon")
        self.right_col.add(
            Box(
                children=[self.water_drop_icon, self.precip],
                orientation="horizontal",
                spacing=2,
            )
        )

        self.today_row.add(self.left_col)
        self.today_row.add(self.center_col)
        self.today_row.add(self.right_col)
        self.add(self.today_row)
        self.add(Separator())

        # --- FORECAST (J+1 / J+2 / J+3) ---
        self.forecast_row = Box(orientation="h", spacing=12)

        self.forecast_cols: list[dict[str, Any]] = []
        for i in range(2):
            col = Box(orientation="v", spacing=6, h_expand=True)
            if i == 0:
                badge = Label(name="weather-popup-dbadge", label="Tomorrow")
            elif i == 1:
                badge = Label(name="weather-popup-dbadge", label="In two days")
            else:
                continue
            date_lbl = Label(name="weather-popup-date", label="--")
            icon = Svg(svg_file=icon_file_from_name("cloud"), size=20)
            icon.add_style_class("weather-icon")
            temps = Label(name="weather-popup-temps", label="-- / --")

            col.add(badge)
            col.add(date_lbl)
            col.add(icon)
            col.add(temps)

            self.forecast_row.add(col)
            self.forecast_cols.append({"badge": badge, "date": date_lbl, "icon": icon, "temps": temps})

        self.add(self.forecast_row)
        self.update(self.weather.data)

    def update(self, data: WeatherServiceData):
        """
        data looks like your sample payload (dict-like).
        """
        city = data.get("city") or "--"
        # If you want city visible somewhere, you can fold it into the title:
        self.title.set_label(f"Today · {city}")
        # Current conditions
        wcode = str(data.get("wCode") or "")
        icon_name = WEATHER_CODE_TO_ICON_NAME.get(wcode, "cloud")
        self.today_icon.set_from_file(icon_file_from_name(icon_name))

        tag = ICON_NAME_TO_TAG.get(icon_name, "—")
        temp = data.get("temp") or "--"
        temp_unit = data.get("temp_unit") or ""
        self.today_text.set_label(f"{tag} · {temp}{temp_unit}")

        # Today sunrise/sunset (prefer forecast[0] if present)
        forecast = data.get("forecast") or []
        if forecast and isinstance(forecast, list) and isinstance(forecast[0], dict):
            self.sunrise.set_label(f"↑ {forecast[0].get('sunrise') or '--'}")
            self.sunset.set_label(f"↓ {forecast[0].get('sunset') or '--'}")
        else:
            self.sunrise.set_label("↑ --")
            self.sunset.set_label("↓ --")

        # Wind / precip under sunrise/sunset
        wind = data.get("wind") or "--"
        wind_unit = data.get("wind_unit") or ""
        wind_dir = data.get("windDir") or ""
        self.wind.set_label(f"{wind}{wind_unit} {wind_dir}".strip())

        precip = data.get("precip")
        precip_unit = data.get("precip_unit") or ""
        precip_txt = "--" if precip in (None, "") else f"{precip}{precip_unit}"
        self.precip.set_label(f"{precip_txt}")

        # J+1..J+3 use forecast[1], [2]if you have them,
        # but your sample only has 3 entries total (today + 2).
        # So: columns map to forecast[1+i] when available.
        for i, col in enumerate(self.forecast_cols):
            f = forecast[1 + i] if len(forecast) > (1 + i) else None

            if not isinstance(f, dict):
                col["date"].set_label("--")
                col["icon"].set_from_file(icon_file_from_name("cloud"))
                col["temps"].set_label("-- / --")
                continue

            # Date formatting
            date_str = f.get("date") or "--"
            pretty_date = self._format_date(date_str)
            col["date"].set_label(pretty_date)

            # Icon
            fcode = str(f.get("wCode") or "")
            fname = WEATHER_CODE_TO_ICON_NAME.get(fcode, "cloud")
            col["icon"].set_from_file(icon_file_from_name(fname))

            # Temps (min/max)
            tmin = f.get("temp_min") or "--"
            tmax = f.get("temp_max") or "--"
            col["temps"].set_label(f"{tmin}{temp_unit} / {tmax}{temp_unit}")

    def _format_date(self, iso_yyyy_mm_dd: str) -> str:
        try:
            d = datetime.strptime(iso_yyyy_mm_dd, "%Y-%m-%d").date()
            return d.strftime("%a %d %b")
        except Exception:
            return iso_yyyy_mm_dd

    def on_before_show(self):
        self.update(self.weather.data)


def tag_from_wcode(wcode: int | str | None) -> str:
    icon_name = icon_name_from_wcode(wcode)
    return ICON_NAME_TO_TAG.get(icon_name, "Unknown")


def icon_name_from_wcode(wcode: int | str | None) -> str:
    if wcode is None:
        return "cloud"
    return WEATHER_CODE_TO_ICON_NAME.get(str(wcode), "cloud")


def icon_file_from_name(name: str) -> str:
    # Adapt to your theme paths
    PROJECT_DIR = os.path.dirname(os.path.realpath(Path(__file__).parent.parent))
    base = PROJECT_DIR + "/styles/pure_black/icons/weather"
    mapping = {
        "clear_day": f"{base}/clear_day.svg",
        "partly_cloudy_day": f"{base}/partly_cloudy_day.svg",
        "cloud": f"{base}/cloud.svg",
        "foggy": f"{base}/foggy.svg",
        "rainy": f"{base}/rainy.svg",
        "thunderstorm": f"{base}/thunderstorm.svg",
        "cloudy_snowing": f"{base}/cloudy_snowing.svg",
        "snowing": f"{base}/snowing.svg",
        "snowing_heavy": f"{base}/snowing_heavy.svg",
        "weather_hail": f"{base}/weather_hail.svg",
        "water_drop": f"{base}/water_drop.svg",
        "wind": f"{base}/wind.svg",
    }
    return mapping.get(name, f"{base}/cloud.svg")


def _fmt_day(day: dict[str, Any], temp_unit: str) -> str:
    icon = icon_name_from_wcode(day.get("wCode"))
    tag = tag_from_wcode(day.get("wCode"))

    tmin = day.get("temp_min", "--")
    tmax = day.get("temp_max", "--")

    # compact column like: clear_day  2–8℃  Clear
    col = f"{icon}  {tmin}–{tmax}{temp_unit}  {tag}"
    return col


class WeatherWidget(PopupWidget):
    def __init__(self, weather: WeatherService, monitor: int = 0, **kwargs: Any):
        self.weather = weather
        self.popup_view = WeatherPopupView(self.weather)
        self.popup = PopupWindow(self.popup_view, on_before_show=self.popup_view.on_before_show, monitor=monitor)

        self.icon = WeatherIcon("cloud")
        self.temp = Label(name="weather-temp", label="--°")

        super().__init__(
            name="weather-widget",
            orientation="h",
            spacing=6,
            main_widget=Box(children=[self.icon, self.temp], name="weather-widget-box"),
            popup_window=self.popup,
            **kwargs,
        )
        self.add_style_class("top-widget")

        self.weather.bind(self._on_weather)
        self.connect("button-press-event", self.on_button_press)

    def _on_weather(self, data: WeatherServiceData):
        if data == {}:
            return
        self.temp.set_label(str(data.get("temp", "--")) + data.get("temp_unit", "°c"))
        try:
            self.icon.set_label(icon_name_from_wcode(data.get("wCode")))
        except Exception:
            raise

        if self.popup.get_visible():
            self.popup_view.update(data)

    def on_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> None:
        if event.button == 1:
            self.on_left_click()

    def on_left_click(self):
        q = quote_plus(f"meteo {self.weather.city}")
        url = f"https://www.google.com/search?q={q}"
        subprocess.Popen(["zen-browser", "--new-tab", url])


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
