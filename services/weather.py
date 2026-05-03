import json
import subprocess
import threading
import time
import warnings
from typing import Any, Callable, TypedDict

from gi.repository import GLib

from services.service import Service


class WeatherForecastDay(TypedDict, total=False):
    date: str
    sunrise: str
    sunset: str
    wCode: str
    temp_max: int | float
    temp_min: int | float
    precip_total: int | float


class WeatherServiceData(TypedDict, total=False):
    uv: int
    humidity: int | float
    sunrise: str
    sunset: str
    windDir: str
    wCode: str
    city: str
    wind: int
    precip: int
    visib: int
    press: int
    temp: int
    temp_feels_like: int
    temp_unit: str
    wind_unit: str
    precip_unit: str
    visib_unit: str
    press_unit: str
    forecast: list[WeatherForecastDay]


def _pick_midday_code(day: dict[str, Any]) -> str:
    # wttr hourly "time" is strings like "0", "300", "600", ..."1200"...
    hourly = day.get("hourly", []) or []
    for h in hourly:
        if str(h.get("time", "")) == "1200":
            return str(h.get("weatherCode", "113"))
    # fallback: first hourly item if present
    if hourly:
        return str((hourly[0] or {}).get("weatherCode", "113"))
    return "113"


def convert_to_sane_hour_format(time: str):
    if " AM" in time:
        return time.removesuffix(" AM")
    elif " PM" in time:
        time = time.removesuffix(" PM")
        h, m = time.split(":")
        return f"{int(h) + 12}:{m}"
    return time


class WeatherService(Service[Any, Any]):
    """
    Non-UI service.
    - Polls wttr.in periodically
    - Exposes .data (dict) and .bind(callback)
    """

    def __init__(
        self,
        city: str,
        fetch_interval_minutes: int = 10,
        use_uscs: bool = False,
        gps_enabled: bool = False,
    ):
        super().__init__()
        self.city = city
        self.use_uscs = use_uscs
        self.gps_enabled = gps_enabled  # TODO implement
        if self.gps_enabled:
            warnings.warn("gps_enabled not implemented yet")

        self.fetch_interval_ms = fetch_interval_minutes * 60 * 1000

        self.location = {"valid": False, "lat": 0.0, "lon": 0.0}

        self._data: WeatherServiceData = {}

        self._callbacks: list[Callable[[WeatherServiceData], None]] = []
        self._lock = threading.Lock()

        threading.Thread(target=self._bg_poll, daemon=True).start()

    def _bg_poll(self):
        raw = None
        i = 0
        while raw is None and i <= 3:
            raw = self._fetch_raw()
            i += 1
            if raw is None:
                time.sleep(10)
        if raw:
            GLib.idle_add(self._apply_raw, raw)
        while True:
            time.sleep(self.fetch_interval_ms / 1000.0)
            raw = self._fetch_raw()
            if raw:
                GLib.idle_add(self._apply_raw, raw)

    @property
    def data(self) -> WeatherServiceData:
        return self._data

    def bind(self, callback: Callable[[WeatherServiceData], None]) -> None:
        self._callbacks.append(callback)
        callback(self.data)

    def _notify(self) -> None:
        for cb in self._callbacks:
            cb(self.data)

    def _format_city(self, city: str) -> str:
        return "+".join(city.strip().split())

    def _build_curl_cmd(self) -> list[str]:
        if self.gps_enabled and self.location["valid"]:
            target = f"{self.location['lat']},{self.location['lon']}"
        else:
            target = self._format_city(self.city)
        return ["curl", "-s", f"wttr.in/{target}?format=j1"]

    def _build_jq_cmd(self) -> list[str]:
        return [
            "jq",
            "{"
            "current: .current_condition[0], "
            "location: .nearest_area[0], "
            "forecast: (.weather[0:3] | map({"
            "  date: .date, "
            "  astronomy: .astronomy[0], "
            "  maxtempC: .maxtempC, maxtempF: .maxtempF, "
            "  mintempC: .mintempC, mintempF: .mintempF, "
            "  totalPrecipMM: .totalPrecipMM, totalPrecipInches: .totalPrecipInches, "
            "  hourly: .hourly"
            "}))"
            "}",
        ]

    def _build_jq_fallback_cmd(self) -> list[str]:
        return [
            "jq",
            "{"
            "current: .data.current_condition[0], "
            "location: (.data.nearest_area[0] // null), "
            "forecast: (.data.weather[0:3] | map({"
            "  date: .date, "
            "  astronomy: .astronomy[0], "
            "  maxtempC: .maxtempC, maxtempF: .maxtempF, "
            "  mintempC: .mintempC, mintempF: .mintempF, "
            "  totalPrecipMM: .totalPrecipMM, totalPrecipInches: .totalPrecipInches, "
            "  hourly: .hourly"
            "}))"
            "}",
        ]

    def _fetch_raw(self) -> dict[str, Any] | None:
        try:
            raw = subprocess.check_output(self._build_curl_cmd(), timeout=10)
            if not raw or not raw.strip():
                return None
            try:
                out = subprocess.check_output(
                    self._build_jq_cmd(), input=raw, timeout=10
                )
                return json.loads(out.decode("utf-8"))
            except Exception:
                out = subprocess.check_output(
                    self._build_jq_fallback_cmd(), input=raw, timeout=10
                )
                return json.loads(out.decode("utf-8"))
        except Exception:
            return None

    def _apply_raw(self, raw: dict[str, Any]) -> None:
        refined = self._refine_data(raw)
        with self._lock:
            self._data = refined
        self._notify()

    def _refine_data(self, data: dict[str, Any]) -> WeatherServiceData:
        current = data.get("current", {}) or {}
        astronomy = data.get("astronomy", {}) or {}
        location = data.get("location", {}) or {}
        forecast_raw = data.get("forecast", []) or []
        forecast: list[WeatherForecastDay] = []
        for day in forecast_raw[:3]:
            astronomy_day = day.get("astronomy", {}) or {}
            wcode = _pick_midday_code(day)

            if self.use_uscs:
                temp_max = day.get("maxtempF", 0)
                temp_min = day.get("mintempF", 0)
                precip_total = day.get("totalPrecipInches", 0)
            else:
                temp_max = day.get("maxtempC", 0)
                temp_min = day.get("mintempC", 0)
                precip_total = day.get("totalPrecipMM", 0)

            forecast.append(
                {
                    "date": str(day.get("date", "")),
                    "sunrise": convert_to_sane_hour_format(
                        str(astronomy_day.get("sunrise", "0.0"))
                    ),
                    "sunset": convert_to_sane_hour_format(
                        str(astronomy_day.get("sunset", "0.0"))
                    ),
                    "wCode": str(wcode),
                    "temp_max": temp_max,
                    "temp_min": temp_min,
                    "precip_total": precip_total,
                }
            )
        sunrise = astronomy.get("sunrise", "0.0")
        sunset = astronomy.get("sunset", "0.0")

        out: WeatherServiceData = {
            "uv": current.get("uvIndex", 0),
            "humidity": current.get("humidity", 0),
            "sunrise": convert_to_sane_hour_format(sunrise),
            "sunset": convert_to_sane_hour_format(sunset),
            "windDir": current.get("winddir16Point", "N"),
            "wCode": current.get("weatherCode", "113"),
            "city": self.city
            or (location.get("areaName", [{}])[0] or {}).get("value", "City"),
            "wind": 0,
            "precip": 0,
            "temp": 0,
            "press": 0,
            "visib": 0,
            "temp_feels_like": 0,
        }

        if self.use_uscs:
            out["wind"] = current.get("windspeedMiles", 0)
            out["precip"] = current.get("precipInches", 0)
            out["visib"] = current.get("visibilityMiles", 0)
            out["press"] = current.get("pressureInches", 0)
            out["temp"] = current.get("temp_F", 0)
            out["temp_feels_like"] = current.get("FeelsLikeF", 0)
            out["temp_unit"] = "℉"
            out["wind_unit"] = "mph"
            out["precip_unit"] = "in"
            out["visib_unit"] = "m"
            out["press_unit"] = "psi"
        else:
            out["wind"] = current.get("windspeedKmph", 0)
            out["precip"] = current.get("precipMM", 0)
            out["visib"] = current.get("visibility", 0)
            out["press"] = current.get("pressure", 0)
            out["temp"] = current.get("temp_C", 0)
            out["temp_feels_like"] = current.get("FeelsLikeC", 0)
            out["temp_unit"] = "℃"
            out["wind_unit"] = "km/h"
            out["precip_unit"] = "mm"
            out["visib_unit"] = "km"
            out["press_unit"] = "hPa"

        out["forecast"] = forecast
        return out
