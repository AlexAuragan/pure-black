import os
import subprocess
import threading
from threading import Timer

from fabric.core.service import Property, Service, Signal
from gi.repository import Gio, GLib
from loguru import logger

from services.hyprland import HyprlandManager


class BrightnessStream(Service):
    @Signal
    def changed(self) -> None:
        ...

    def __init__(self, name: str, device_path: str, is_external: bool = False, **kwargs):
        self._model = kwargs.pop("model", None)
        self._mfg = kwargs.pop("mfg", None)
        self._serial = kwargs.pop("serial", None)
        self._connector_name = kwargs.pop("connector_name", None)
        super().__init__(**kwargs)
        self._name = name
        self._device_path = device_path
        self._is_external = is_external
        self._debounce_timer = None
        self._cached_brightness = 50.0 if is_external else self._get_initial_brightness()
        if not self._is_external:
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_external(self) -> bool:
        return self._is_external

    @property
    def serial(self) -> str | None:
        return self._serial

    @property
    def model(self) -> str | None:
        return self._model

    @property
    def connector_name(self) -> str | None:
        return self._connector_name

    @Property(float, "read-write")
    def screen_brightness(self) -> float:
        return self._cached_brightness

    @screen_brightness.setter
    def screen_brightness(self, value: float):
        value = max(0, min(100, float(value)))

        # avoid tiny float oscillations and redundant writes
        if abs(value - self._cached_brightness) < 0.5:
            return

        self._cached_brightness = value

        if self._is_external:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = Timer(0.1, self._apply_external_brightness, [value])
            self._debounce_timer.start()
        else:
            self._apply_internal_brightness(value)

        self.changed()
        self.notify("screen-brightness")
    def _get_initial_brightness(self) -> float:
        try:
            if self._is_external:
                cmd = f"ddcutil getvcp 10 --bus {self._device_path} --terse"
                output = subprocess.check_output(cmd.split(), stderr=subprocess.DEVNULL, timeout=2).decode().split()
                return float(output[3])
            else:
                return self._read_sysfs()
        except Exception:
            return 50.0

    def _read_sysfs(self) -> float:
        path = f"/sys/class/backlight/{self._device_path}"
        with open(f"{path}/brightness", "r") as file:
            current_brightness = int(file.read().strip())
        with open(f"{path}/max_brightness", "r") as file:
            max_brightness = int(file.read().strip())
        return (current_brightness / max_brightness) * 100

    def _apply_internal_brightness(self, value: int):
        try:
            variant = GLib.Variant("(ssu)", ("backlight", self._device_path, int(value)))
            self._bus.call_sync(
                "org.freedesktop.login1", "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager", "SetBrightness",
                variant, None, Gio.DBusCallFlags.NONE, -1, None
            )
        except Exception:
            subprocess.Popen(["brightnessctl", "-d", self._device_path, "s", f"{value}%"])

    def _apply_external_brightness(self, value: int):
        bus_number = self._device_path.replace("/dev/i2c-", "")
        try:
            subprocess.run(
                ["ddcutil", "setvcp", "10", str(int(value)), "--bus", bus_number,
                 "--noverify", "--sleep-multiplier", ".1"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
            )
        except subprocess.TimeoutExpired:
            logger.error("ddcutil command timed out")
        except Exception as exception:
            logger.error(f"Error applying brightness: {exception}")


class Brightness(Service):
    @Signal
    def changed(self) -> None:
        ...

    @Signal
    def screen_added(self) -> None:
        ...

    def __init__(self, hyprland: HyprlandManager, **kwargs):
        super().__init__(**kwargs)
        self._hyprland = hyprland
        self._screens: list[BrightnessStream] = []
        self._hyprland.connect("notify::monitors", self._on_monitors_changed)
        self._scan_source_id: int | None = None
        self._last_monitors_sig: tuple | None = None
        self._last_ddc_scan_ts = 0.0
        self._scan_thread_running = False
        self._scan_requested = False
        self._schedule_scan(initial=True)

    @Property(list, "readable")
    def screens(self) -> list[BrightnessStream]:
        return self._screens

    def scan_screens(self):
        existing_streams = {}
        for stream in self._screens:
            key = (stream.serial or stream._device_path) if stream.is_external else stream._device_path
            existing_streams[key] = stream
        new_screens = []
        try:
            if os.path.exists("/sys/class/backlight"):
                for backlight_device in os.listdir("/sys/class/backlight"):
                    if backlight_device in existing_streams:
                        new_screens.append(existing_streams[backlight_device])
                    else:
                        new_screens.append(BrightnessStream(
                            name=f"Internal: {backlight_device}",
                            device_path=backlight_device,
                            is_external=False
                        ))
        except Exception:
            pass
        try:
            output = subprocess.check_output(
                ["ddcutil", "detect", "--terse", "--sleep-multiplier", ".1"],
                stderr=subprocess.DEVNULL
            ).decode(errors="replace")
            displays: list[dict] = []
            current_display: dict = {}

            def flush_display():
                nonlocal current_display
                if current_display:
                    displays.append(current_display)
                    current_display = {}

            for raw_line in output.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                line_lower = line.lower()
                if line_lower.startswith("display"):
                    flush_display()
                    continue
                if line_lower.startswith("i2c bus:"):
                    current_display["bus"] = line.split(":", 1)[1].strip()
                    continue
                if line_lower.startswith("mfg id:"):
                    current_display["mfg"] = line.split(":", 1)[1].strip()
                    continue
                if line_lower.startswith(("model:", "model name:", "display model:", "display model name:",
                                          "monitor:", "monitor name:")):
                    current_display["model"] = line.split(":", 1)[1].strip()
                    continue
                if line_lower.startswith(("serial", "serial number:", "serial no:", "sn:")):
                    current_display["serial"] = line.split(":", 1)[1].strip()
                    continue
            flush_display()

            for display in displays:
                bus = display.get("bus")
                if not bus:
                    continue
                model = display.get("model") or "Unknown"
                mfg = display.get("mfg")
                serial = display.get("serial")
                key = serial or bus
                if key in existing_streams:
                    new_screens.append(existing_streams[key])
                else:
                    pretty_name = model if not mfg else f"{model} ({mfg})"
                    new_screens.append(BrightnessStream(
                        name=pretty_name, device_path=bus, is_external=True,
                        model=model, mfg=mfg, serial=serial
                    ))
        except Exception as exception:
            logger.warning(f"DDC Scan failed: {exception}")
        self._screens = new_screens
        self.changed()
        self.notify("screens")

    def _monitors_signature(self) -> tuple:
        # Only include fields that reflect physical monitor topology
        # (name/description/model/serial are stable; active workspace is NOT)
        mons = self._hyprland.monitors or {}
        items = []
        for mid, m in mons.items():
            items.append((
                int(mid),
                (m.get("name") or ""),
                (m.get("description") or ""),
                (m.get("model") or ""),
                (m.get("serial") or ""),
            ))
        items.sort()
        return tuple(items)

    def _on_monitors_changed(self, *_):
        sig = self._monitors_signature()
        if sig == self._last_monitors_sig:
            return
        self._last_monitors_sig = sig
        self._schedule_scan()

    def _schedule_scan(self, initial: bool = False):
        if self._scan_source_id is not None:
            GLib.Source.remove(self._scan_source_id)
            self._scan_source_id = None

        delay_ms = 0 if initial else 250
        self._scan_source_id = GLib.timeout_add(delay_ms, self._run_scan)

    def _run_scan(self):
        self._scan_source_id = None

        # coalesce if a scan is already running
        if self._scan_thread_running:
            self._scan_requested = True
            return False

        self._scan_thread_running = True
        self._scan_requested = False

        # snapshot current streams so the worker doesn't touch GTK objects
        existing = {}
        for stream in self._screens:
            key = (stream.serial or stream._device_path) if stream.is_external else stream._device_path
            existing[key] = stream

        def worker(existing_streams_snapshot: dict):
            try:
                result = self._scan_screens_compute(existing_streams_snapshot)
            except Exception as e:
                result = e
            GLib.idle_add(self._scan_screens_apply, result)

        threading.Thread(target=worker, args=(existing,), daemon=True).start()
        return False

    def _scan_screens_compute(self, existing_streams: dict):
        new_screens: list[BrightnessStream | tuple] = []

        if os.path.exists("/sys/class/backlight"):
            for backlight_device in os.listdir("/sys/class/backlight"):
                if backlight_device in existing_streams:
                    new_screens.append(existing_streams[backlight_device])
                else:
                    new_screens.append(("create_internal", backlight_device))

        output = subprocess.check_output(
            ["ddcutil", "detect", "--terse", "--sleep-multiplier", ".1"],
            stderr=subprocess.DEVNULL,
        ).decode(errors="replace")

        displays: list[dict] = []
        current: dict = {}

        def flush():
            nonlocal current
            if current:
                displays.append(current)
                current = {}

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                flush()
                continue

            ll = line.lower()

            if ll.startswith("display "):
                flush()
                continue

            if ll == "invalid display":
                current["invalid"] = True
                continue

            if ll.startswith("i2c bus:"):
                current["bus"] = line.split(":", 1)[1].strip()
                continue

            if ll.startswith("drm connector:"):
                drm_connector = line.split(":", 1)[1].strip()
                current["drm_connector"] = drm_connector
                current["connector_name"] = drm_connector.split("-", 1)[1] if "-" in drm_connector else drm_connector
                continue

            if ll.startswith("drm_connector_id:"):
                current["drm_connector_id"] = line.split(":", 1)[1].strip()
                continue

            if ll.startswith("monitor:"):
                monitor_value = line.split(":", 1)[1].strip()
                current["monitor_raw"] = monitor_value

                parts = monitor_value.split(":", 2)
                current["mfg"] = parts[0].strip() if len(parts) > 0 and parts[0].strip() else None
                current["model"] = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                current["serial"] = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
                continue

        flush()

        for d in displays:
            bus = d.get("bus")
            connector_name = d.get("connector_name")
            model = d.get("model")
            mfg = d.get("mfg")
            serial = d.get("serial")

            if not bus:
                continue

            if connector_name and connector_name.lower().startswith("edp"):
                continue

            if not connector_name:
                continue

            if not model:
                continue

            key = serial or bus

            if key in existing_streams:
                new_screens.append(existing_streams[key])
            else:
                new_screens.append(("create_external", {
                    "bus": bus,
                    "model": model,
                    "mfg": mfg,
                    "serial": serial,
                    "connector_name": connector_name,
                }))

        return new_screens

    def _scan_screens_compute(self, existing_streams: dict):
        new_screens: list[BrightnessStream | tuple] = []

        if os.path.exists("/sys/class/backlight"):
            for backlight_device in os.listdir("/sys/class/backlight"):
                if backlight_device in existing_streams:
                    new_screens.append(existing_streams[backlight_device])
                else:
                    new_screens.append(("create_internal", backlight_device))

        output = subprocess.check_output(
            ["ddcutil", "detect", "--terse", "--sleep-multiplier", ".1"],
            stderr=subprocess.DEVNULL,
        ).decode(errors="replace")

        displays: list[dict] = []
        current: dict = {}

        def flush():
            nonlocal current
            if current:
                displays.append(current)
                current = {}

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                flush()
                continue

            ll = line.lower()

            if ll.startswith("display "):
                flush()
                continue

            if ll == "invalid display":
                current["invalid"] = True
                continue

            if ll.startswith("i2c bus:"):
                current["bus"] = line.split(":", 1)[1].strip()
                continue

            if ll.startswith("drm connector:"):
                drm_connector = line.split(":", 1)[1].strip()
                current["drm_connector"] = drm_connector
                current["connector_name"] = drm_connector.split("-", 1)[1] if "-" in drm_connector else drm_connector
                continue

            if ll.startswith("drm_connector_id:"):
                current["drm_connector_id"] = line.split(":", 1)[1].strip()
                continue

            if ll.startswith("monitor:"):
                monitor_value = line.split(":", 1)[1].strip()
                current["monitor_raw"] = monitor_value

                parts = monitor_value.split(":", 2)
                current["mfg"] = parts[0].strip() if len(parts) > 0 and parts[0].strip() else None
                current["model"] = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                current["serial"] = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
                continue

        flush()

        for d in displays:
            bus = d.get("bus")
            connector_name = d.get("connector_name")
            model = d.get("model")
            mfg = d.get("mfg")
            serial = d.get("serial")

            if not bus:
                continue

            if connector_name and connector_name.lower().startswith("edp"):
                continue

            if not connector_name:
                continue

            if not model:
                continue

            key = serial or bus

            if key in existing_streams:
                new_screens.append(existing_streams[key])
            else:
                new_screens.append(("create_external", {
                    "bus": bus,
                    "model": model,
                    "mfg": mfg,
                    "serial": serial,
                    "connector_name": connector_name,
                }))

        return new_screens

    def get_screen_for_monitor(self, monitor_id: int) -> BrightnessStream | None:
        hypr_monitor = self._hyprland.monitors.get(monitor_id)
        if not hypr_monitor:
            return None

        hypr_name = (hypr_monitor.get("name", "") or "").lower()
        hypr_model = (hypr_monitor.get("model", "") or "").lower()
        hypr_description = (hypr_monitor.get("description", "") or "").lower()
        hypr_serial = (hypr_monitor.get("serial", "") or "").lower()

        if hypr_name.startswith("edp"):
            for stream in self._screens:
                if not stream.is_external:
                    return stream
            return None

        for stream in self._screens:
            if not stream.is_external:
                continue

            stream_connector = (stream.connector_name or "").lower()
            stream_model = (stream.model or "").lower()
            stream_serial = (stream.serial or "").lower()

            if stream_connector and stream_connector == hypr_name:
                return stream

            if stream_serial and hypr_serial and stream_serial == hypr_serial:
                return stream

            if stream_model and (
                    stream_model in hypr_model
                    or stream_model in hypr_description
                    or hypr_model in stream_model
            ):
                return stream

        return None

    def _scan_screens_apply(self, result):
        self._scan_thread_running = False

        if isinstance(result, Exception):
            logger.warning(f"Brightness scan failed: {result}")
            if self._scan_requested:
                self._schedule_scan()
            return False

        new_screens: list[BrightnessStream] = []
        existing_streams = {}
        for stream in self._screens:
            key = (stream.serial or stream._device_path) if stream.is_external else stream._device_path
            existing_streams[key] = stream

        for item in result:
            if isinstance(item, BrightnessStream):
                new_screens.append(item)
                continue

            tag, payload = item
            if tag == "create_internal":
                backlight_device = payload
                new_screens.append(BrightnessStream(
                    name=f"Internal: {backlight_device}",
                    device_path=backlight_device,
                    is_external=False,
                ))
            elif tag == "create_external":
                info = payload
                bus = info["bus"]
                model = info.get("model") or "Unknown"
                mfg = info.get("mfg")
                serial = info.get("serial")
                connector_name = info.get("connector_name")
                pretty_name = model if not mfg else f"{model} ({mfg})"
                new_screens.append(BrightnessStream(
                    name=pretty_name,
                    device_path=bus,
                    is_external=True,
                    model=model,
                    mfg=mfg,
                    serial=serial,
                    connector_name=connector_name,
                ))

        self._screens = new_screens
        self.changed()
        self.notify("screens")

        if self._scan_requested:
            self._schedule_scan()

        return False