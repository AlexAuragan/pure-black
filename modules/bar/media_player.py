# WIP

from pathlib import Path

from fabric.audio.service import Audio, AudioStream
from fabric.widgets.box import Box
from fabric.widgets.eventbox import EventBox
from fabric.widgets.image import Image
from fabric.widgets.svg import Svg

from gi.overrides import Gio
from gi.repository.GObject import ParamSpecBoxed
from gi.repository import Cvc

from components import Svg
from components.popup_widget import PopupWidget, PopupWindow

from gi.repository import Gdk

BASE_ICON_PATH = Path("styles") / "pure_black" / "icons" / "pc"


class Application(EventBox):
    def __init__(self, app: AudioStream):
        self.name: str = app.name
        self.description: str = app.description
        self.state: str = app.state
        self.icon_name: str = app.icon_name
        self.type: str = app.description
        self.stream: Cvc.MixerStream = app.stream
        gicon: Gio.ThemedIcon = self.stream.get_gicon()
        names = gicon.get_names()

        super().__init__(child=Image(icon_name=names[0], icon_size=24))


class ApplicationList(PopupWindow):
    def __init__(self, audio_service: Audio):
        self.audio_service = audio_service
        self.applications: list[Application] = []
        self.box = Box(children=self.applications)

        super().__init__(
            name="scale-window",
            child_view=self.box,
            use_revealer=True,
        )
        self.show()

    def on_applications_set(self, audio: Audio, event: ParamSpecBoxed):
        apps = []
        for app in audio.applications:
            apps.append(Application(app))
        self.applications = apps
        self.box.children = apps


class MediaIcon(Box):
    def __init__(self, audio_service: Audio, volume=0):
        self.audio_service = audio_service
        self._volume: int = volume
        self.icon = Svg(self.volume_to_path(), size=24)
        super().__init__(
            children=[self.icon],
            all_visible=True,
            orientation="vertical",
            spacing=4,
            v_align="center",
        )

    def volume_to_path(self):
        return BASE_ICON_PATH / "volume_full.svg"


class MediaPlayer(PopupWidget):
    def __init__(self, audio_service: Audio):
        self.audio_service = audio_service
        self.sound_icon = MediaIcon(self.audio_service)
        self.popup_window = ApplicationList(self.audio_service)
        super().__init__(
            name="media-player",
            main_widget=self.sound_icon,
            popup_window=self.popup_window,
            all_visible=True,
            events="scroll",
            interactive=True,
        )
        self.add_style_class("top-widget")

        self.audio_service.connect("notify::applications", self.popup_window.on_applications_set)
        self.connect("button-press-event", self.on_button_press)

    @staticmethod
    def on_button_press(widget, event):
        if event.button == 1:
            widget.on_left_click()

    def on_left_click(self):
        pass
        # subprocess.Popen(["pavucontrol"])
