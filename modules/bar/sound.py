import subprocess
from pathlib import Path

from fabric.audio.service import Audio, AudioStream
from fabric.widgets.box import Box
from fabric.widgets.eventbox import EventBox
from fabric.widgets.scale import Scale

from components import Svg
from components.popup_widget import PopupWidget, PopupWindow

from gi.repository import Gdk

BASE_ICON_PATH = Path(__file__).parent.parent.parent / "styles" / "pure_black" / "icons" / "pc"

class SoundScale(EventBox):
    def __init__(self, audio_service: Audio):
        self.audio_service = audio_service
        self.volume_bar = Scale(
            name="volume-bar",
            max_value=100, min_value=0, value=55, orientation="vertical", size=(4, 120),
            v_align="center",
            events="scroll",
        )

        super().__init__(
            name="scale-window",
            child=self.volume_bar,
        )
        self.show()
        self._syncing = False
        self.volume_bar.connect("value-changed", self._on_bar_changed)
        self.audio_service.connect("notify::speaker", self._on_speaker_set)
        self.volume_bar.connect("scroll-event", self.on_scroll)


    def _on_speaker_set(self, service, event):
        if service.speaker:
            service.speaker.connect("notify::volume", self._on_service_volume_changed)
            self._sync_bar(service.speaker.volume)


    def _on_service_volume_changed(self, speaker, event):
        self._sync_bar(speaker.volume)

    def _sync_bar(self, volume: float):
        self._syncing = True
        self.volume_bar.set_value(volume)
        self._syncing = False

    def _on_bar_changed(self, scale):
        if self._syncing:
            return
        if self.audio_service.speaker:
            self.audio_service.speaker.volume = max(0, min(100, scale.value))


    def change_volume(self, delta: int):
        if self.audio_service.speaker is None:
            return
        new_vol = self.audio_service.speaker.volume + delta
        self.audio_service.speaker.volume = max(0, min(100, new_vol))

    def on_scroll(self, widget, event):
        # The scale gives a smooth direction
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            success, delta_x, delta_y = event.get_scroll_deltas()
            if not success:
                return
            if delta_y > 0:
                self.change_volume(-8)
            elif delta_y < 0:
                self.change_volume(8)
            return

        match event.direction:
            case Gdk.ScrollDirection.UP:
                self.change_volume(8)
            case Gdk.ScrollDirection.DOWN:
                self.change_volume(-8)
        return

class SoundIcon(Box):
    def __init__(self, audio_service: Audio, volume=0):
        self.audio_service = audio_service
        self._volume: int = volume
        self.icon = Svg(self.volume_to_path(), size=24)
        super().__init__(
            children=[self.icon],
            all_visible=True,
            orientation="vertical",
            spacing=4,
            v_align="center"
        )

    def on_volume_change(self, service: AudioStream, event):
        self.volume = service.volume

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int):
        assert 0 <= value <= 100
        self._volume = value
        self.icon.set_from_file(str(self.volume_to_path()))

    def volume_to_path(self) -> Path:
        if self.volume == 0:
            return BASE_ICON_PATH / "volume_mute.svg"
        if self.volume <= 50:
            return BASE_ICON_PATH / "volume_half.svg"
        return BASE_ICON_PATH / "volume_full.svg"

    def on_speaker_set(self):
        self.audio_service.speaker.connect("notify::volume", self.on_volume_change)

class Sound(PopupWidget):
    def __init__(self, audio_service: Audio):
        self.audio_service = audio_service
        self.sound_icon = SoundIcon(self.audio_service)
        self.popup_view = SoundScale(self.audio_service)
        self.popup_window = PopupWindow(self.popup_view)
        super().__init__(
            name="media-player",
            main_widget=self.sound_icon,
            popup_window=self.popup_window,
            all_visible=True,
            events="scroll",
            interactive=True
        )
        self.add_style_class("top-widget")

        self.audio_service.connect("notify::speaker", self.sound_icon.on_speaker_set)
        self.connect("scroll-event", self.on_scroll)
        self.connect("button-press-event", self.on_button_press)


    def change_volume(self, delta: int):
        if self.audio_service.speaker is None:
            return
        new_vol = self.audio_service.speaker.volume + delta
        self.audio_service.speaker.volume = max(0, min(100, new_vol))

    def on_scroll(self, _, event):
        self.popup_view.on_scroll(_, event)

    @staticmethod
    def on_button_press(widget, event):
        if event.button == 1:
            widget.on_left_click()

    def on_left_click(self):
        subprocess.Popen(["pavucontrol"])