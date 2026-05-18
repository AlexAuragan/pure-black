import subprocess
from pathlib import Path
from typing import Any
from loguru import logger

from fabric.widgets.box import Box
from fabric.widgets.eventbox import EventBox
from fabric.widgets.scale import Scale

from components import Svg
from components.popup_widget import PopupWidget, PopupWindow


from gi.repository import Gdk, Gtk

from services.brightness import BrightnessStream, Brightness

BASE_ICON_PATH = Path(__file__).parent.parent.parent / "styles" / "pure_black" / "icons" / "pc"


class BrightnessScale(EventBox):
    def __init__(self, brightness_service: Brightness, screen_id: int):
        self.brightness_service = brightness_service
        self.screen_id = screen_id
        self._syncing = False
        self._handler_id = None  # Track the signal
        self._current_stream = None

        self.brightness_bar = Scale(
            name="brightness-bar",
            max_value=100,
            min_value=0,
            value=50,
            orientation="vertical",
            size=(4, 120),
            v_align="center",
            events="scroll",
        )

        super().__init__(name="brightness-scale-window", child=self.brightness_bar)
        self.brightness_bar.connect("value-changed", self._on_bar_changed)
        self.brightness_bar.connect("scroll-event", self.on_scroll)

    def update_stream(self, stream: BrightnessStream | None):
        # 1. Disconnect old stream
        if self._current_stream and self._handler_id:
            self._current_stream.disconnect(self._handler_id)

        self._current_stream = stream

        # 2. Connect new stream
        if stream:
            self._handler_id = stream.connect(
                "notify::screen-brightness",
                lambda s, e: self._sync_bar(s.screen_brightness),
            )
            self._sync_bar(stream.screen_brightness)

    def _sync_bar(self, value: float):
        if self._syncing:
            return
        self._syncing = True
        self.brightness_bar.set_value(value)
        self._syncing = False

    def _on_bar_changed(self, scale: Scale) -> None:
        if self._syncing or not self._current_stream:
            return
        self._current_stream.screen_brightness = float(scale.get_value())

    def change_brightness(self, delta: int):
        if not self._current_stream:
            return
        new_val = self._current_stream.screen_brightness + delta
        self._current_stream.screen_brightness = max(0, min(100, new_val))

    def on_scroll(self, widget: Gtk.Widget, event: Gdk.Event) -> None:
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            success, _, delta_y = event.get_scroll_deltas()
            if success:
                self.change_brightness(-8 if delta_y > 0 else 8)
        elif event.direction == Gdk.ScrollDirection.UP:
            self.change_brightness(8)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.change_brightness(-8)


class BrightnessIcon(Box):
    def __init__(self, brightness_service: Brightness, screen_id: int):
        self._handler_id = None
        self._current_stream: BrightnessStream | None = None
        self._brightness: float = 0

        self.icon = Svg(str(BASE_ICON_PATH / "brightness_empty.svg"), size=24)
        super().__init__(children=[self.icon], all_visible=True, v_align="center")

    def update_stream(self, stream: BrightnessStream | None):
        if self._current_stream and self._handler_id:
            self._current_stream.disconnect(self._handler_id)

        self._current_stream = stream
        if stream:
            self._handler_id = stream.connect(
                "notify::screen-brightness",
                lambda s, e: self._update_icon(s.screen_brightness),
            )
            self._update_icon(stream.screen_brightness)

    def _update_icon(self, value: float):
        self._brightness = value
        # Map 0-100 to icons
        icon_name = "brightness_empty.svg"
        if value > 66:
            icon_name = "brightness_high.svg"
        elif value > 33:
            icon_name = "brightness_low.svg"

        self.icon.set_from_file(str(BASE_ICON_PATH / icon_name))


class BrightnessWidget(PopupWidget):
    def __init__(self, brightness_service: Brightness, screen_id: int = 0):
        self.brightness_service = brightness_service
        self.screen_id = screen_id

        self.brightness_icon = BrightnessIcon(self.brightness_service, self.screen_id)
        self.popup_view = BrightnessScale(self.brightness_service, self.screen_id)
        self.popup_window = PopupWindow(self.popup_view)

        super().__init__(
            name="brightness-widget",
            main_widget=self.brightness_icon,
            popup_window=self.popup_window,
            all_visible=True,
            events="scroll",
            interactive=True,
        )

        self.add_style_class("top-widget")
        self.connect("scroll-event", self.on_scroll)
        self.connect("button-press-event", self.on_button_press)
        self.brightness_service.connect("changed", self._on_brightness_changed)

        self._on_brightness_changed()

    def _on_brightness_changed(self, *args: Any) -> None:
        # Get the specific stream from the service
        match = self.brightness_service.get_screen_for_monitor(self.screen_id)

        # Update the UI components with the new stream (or None)
        self.brightness_icon.update_stream(match)
        self.popup_view.update_stream(match)

    def on_scroll(self, _: Gtk.Widget, event: Gdk.Event) -> None:
        self.popup_view.on_scroll(_, event)

    @staticmethod
    def on_button_press(widget: Gtk.Widget, event: Gdk.Event) -> None:
        if event.button == 1:
            # TODO Maybe open display settings ?
            subprocess.Popen(["wdisplays"])

    def change_brightness(self, delta: int):
        self.popup_view.change_brightness(delta)
