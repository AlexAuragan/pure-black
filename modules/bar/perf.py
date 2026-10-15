import os
import subprocess
import threading
import time
from typing import Any
from pathlib import Path

import psutil
from fabric import Fabricator
from fabric.widgets.box import Box
from fabric.widgets.circularprogressbar import CircularProgressBar
from fabric.widgets.scale import Scale
from fabric.widgets.label import Label
from fabric.widgets.separator import Separator
from fabric.widgets.wayland import WaylandWindow
from fabric.widgets.widget import Widget

from components import Svg

from gi.repository import GLib, Gdk, Gtk

from components.popup_widget import PopupWidget, PopupWindow
from services.battery import Battery
from utils.widget_utils import position_under

PROJECT_DIR = os.path.dirname(os.path.realpath(Path(__file__).parent.parent))

GAP = 4


class PerfPopupView(Box):
    def __init__(self, **kwargs: Any):
        super().__init__(
            name="perf-popup",
            orientation="v",
            spacing=12,
            style="padding: 15px; min-width: 380px;",  # Widened for dual columns
            **kwargs,
        )
        self.is_init: bool = False
        # --- CPU & RAM Bars ---
        self.res_row = Box(orientation="h", spacing=20)

        # CPU Column
        self.cpu_col = Box(orientation="v", spacing=4, h_expand=True)
        self.cpu_col.add(
            Label(
                label="CPU",
                x_align=0,
                style="font-weight: bold; color: var(--accent1);",
            )
        )
        self.cpu_label = Label(label="0%", x_align=0)
        self.cpu_bar = Scale(name="popup-cpu-bar", orientation="h")
        self.cpu_bar.add_style_class("perf-bar")
        self.cpu_col.add(self.cpu_label)
        self.cpu_col.add(self.cpu_bar)

        # RAM Column
        self.ram_col = Box(orientation="v", spacing=4, h_expand=True)
        self.ram_col.add(
            Label(
                label="MEM",
                x_align=0,
                style="font-weight: bold; color: var(--accent2);",
            )
        )
        self.ram_label = Label(label="0/0 GB", x_align=0)
        self.ram_bar = Scale(name="popup-ram-bar", orientation="h")
        self.ram_bar.add_style_class("perf-bar")
        self.ram_col.add(self.ram_label)
        self.ram_col.add(self.ram_bar)

        self.res_row.add(self.cpu_col)
        self.res_row.add(self.ram_col)
        self.add(self.res_row)

        self.add(Separator())

        # --- Processes (Dual Column) ---
        self.proc_container = Box(orientation="h", spacing=15)

        # Left Column: Top CPU
        self.cpu_proc_col = Box(orientation="v", spacing=4, h_expand=True)
        self.cpu_proc_col.add(
            Label(
                label="TOP BY CPU",
                x_align=0,
                style="font-weight: bold; font-size: 10px; color: var(--accent3);",
            )
        )
        self.cpu_proc_list = Label(label="...", x_align=0, style="font-family: monospace; font-size: 11px;")
        self.cpu_proc_col.add(self.cpu_proc_list)

        # Right Column: Top RAM
        self.mem_proc_col = Box(orientation="v", spacing=4, h_expand=True)
        self.mem_proc_col.add(
            Label(
                label="TOP BY MEM",
                x_align=0,
                style="font-weight: bold; font-size: 10px; color: var(--accent4);",
            )
        )
        self.mem_proc_list = Label(label="...", x_align=0, style="font-family: monospace; font-size: 11px;")
        self.mem_proc_col.add(self.mem_proc_list)

        self.proc_container.add(self.cpu_proc_col)
        self.proc_container.add(self.mem_proc_col)
        self.add(self.proc_container)

        self.add(Separator())

    def update_display(self, data: dict[str, Any]) -> None:
        if not self.get_visible():
            return
        self.is_init = True
        cpu_p = data["cpu"]
        mem = data["ram"]
        total_ram_gb = mem.total / (1024**3)

        # Update resource bars
        self.cpu_label.set_label(f"{cpu_p}%")
        self.cpu_bar.set_value(cpu_p / 100)
        self.ram_label.set_label(f"{mem.used / (1024 ** 3):.1f}/{total_ram_gb:.1f}GB")
        self.ram_bar.set_value(mem.percent / 100)

        # Process the processes (already fetched by the service)
        procs = data["procs"]

        # CPU Top 3
        top_cpu = sorted(procs, key=lambda x: x["cpu_percent"], reverse=True)[:3]
        self.cpu_proc_list.set_label(
            "".join(
                [
                    f"{(p['name'][:10] + '..') if len(p['name']) > 10 else p['name'].ljust(12)} {p['cpu_percent']:>4.0f}%\n"
                    for p in top_cpu
                ]
            )
        )

        # RAM Top 3
        top_mem = sorted(procs, key=lambda x: x["memory_percent"], reverse=True)[:3]
        self.mem_proc_list.set_label(
            "".join(
                [
                    f"{(p['name'][:8] + '..') if len(p['name']) > 8 else p['name'].ljust(10)} "
                    f"{p['memory_info'].rss / (1024 ** 3):>4.1f}G {p['memory_percent']:>3.0f}%\n"
                    for p in top_mem
                ]
            )
        )


class PerfPopupWindow(WaylandWindow):
    def __init__(self, perf_data: Fabricator[Any], **kwargs: Any):
        self.view = PerfPopupView()
        super().__init__(
            name="perf-popup-window",
            layer="overlay",
            type="popup",
            anchor="top left",
            child=self.view,
            visible=False,
            **kwargs,
        )
        self.pass_through = True
        self.compute_repeater = None
        perf_data.connect("changed", self.on_data_received)

    def on_data_received(self, fabricator: Fabricator[Any], data: dict[str, Any]) -> None:
        # Only update the labels if the popup is actually visible to save CPU
        if self.get_visible() or not self.view.is_init:
            self.view.update_display(data)

    def open(self, widget: Widget) -> None:
        position_under(widget, self)
        self.set_visible(True)

    def close(self):
        self.set_visible(False)
        if self.compute_repeater:
            self.compute_repeater = None


class PerfWidget(PopupWidget):
    def __init__(self, battery_service: Battery, monitor: int = 0):
        base = PROJECT_DIR + "/styles/pure_black/icons/pc/"
        self._icon_dir = base
        self.battery_service = battery_service
        cpu_icon = Svg(base + "cpu.svg", icon_size=12)
        cpu_icon.set_name("perf_icon")
        ram_icon = Svg(base + "memory.svg", icon_size=12)
        ram_icon.set_name("perf_icon")
        self._current_battery_icon = "battery_7.svg"
        self.battery_icon = Svg(base + self._current_battery_icon, icon_size=12)
        self.battery_icon.set_name("perf_icon")

        self.cpu_widget = CircularProgressBar(
            name="cpu-progress-bar",
            pie=True,
            child=cpu_icon,
            size=24,
        )
        self.ram_widget = CircularProgressBar(
            name="ram-progress-bar",
            pie=True,
            child=ram_icon,
            size=24,
        )

        self.battery_widget = CircularProgressBar(
            name="battery-progress-bar",
            pie=True,
            child=self.battery_icon,
            size=24,
        )

        self.popup_view = PerfPopupView()
        self.popup = PopupWindow(self.popup_view, monitor=monitor)

        children = [self.cpu_widget, self.ram_widget]

        if self.battery_service.present:
            children.append(self.battery_widget)

        self._inner = Box(children=children, spacing=4, name="perf")
        super().__init__(name="perf", main_widget=self._inner, popup_window=self.popup)
        self.add_style_class("top-widget")
        self.connect("button-press-event", self.on_button_press)
        self.battery_service.connect("changed", self._on_battery_changed)
        self._on_battery_changed()
        self._stop = threading.Event()
        self.connect("destroy", lambda *_: self._stop.set())
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                procs = []
                for p in psutil.process_iter(["name", "cpu_percent", "memory_percent", "memory_info"], ad_value=None):
                    try:
                        procs.append(p.info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                        pass
                data = {
                    "cpu": psutil.cpu_percent(),
                    "ram": psutil.virtual_memory(),
                    "procs": procs,
                }
                if not self._stop.is_set():
                    GLib.idle_add(self.on_perf_changed, data)
            except Exception:
                pass
            self._stop.wait(1)

    def on_perf_changed(self, data: dict[str, Any]):
        self.cpu_widget.value = data["cpu"] / 100
        self.ram_widget.value = data["ram"].percent / 100
        if self.popup.get_visible():
            self.popup_view.update_display(data)

    def _on_battery_changed(self, *_) -> None:
        service = self.battery_service
        if not service.present:
            return
        self.battery_widget.value = service.percent / 100
        self._update_battery_icon(service.percent, service.charging)

    def _update_battery_icon(self, percent: float | None, power_plugged: bool | None) -> None:
        name = self._battery_icon_name(percent, power_plugged)
        if name == self._current_battery_icon:
            return
        self._current_battery_icon = name
        self.battery_icon.set_from_file(self._icon_dir + name)

    @staticmethod
    def _battery_icon_name(percent: float | None, power_plugged: bool | None) -> str:
        # no reading at all -> "unknown" fallback (shouldn't show on desktops)
        if percent is None:
            return "battery_error.svg"
        # plugged in -> charging icon
        if power_plugged:
            return "battery_charging.svg"
        # 8 levels (0 = empty/alert ... 7 = full), each spanning 12.5%
        level = max(0, min(7, int(percent * 8 / 100)))
        return f"battery_{level}.svg"

    def on_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> None:
        if event.button == 1:
            self.on_left_click()

    @staticmethod
    def on_left_click():
        subprocess.Popen(["kitty", "--start-as=fullscreen", "btop"])
