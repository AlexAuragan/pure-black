from fabric.widgets.box import Box
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow

from fabric.audio.service import Audio, AudioStream

from components.tabs import TabSpec, Tabs
from modules.audioctl.stream_row import StreamRow


class StreamListPage(Box):
    """
    A scrollable list of StreamRow widgets.
    Rebuilds on Audio.changed and also on default device changes.
    """

    def __init__(self, audio: Audio, kind: str):
        self.audio = audio
        self.kind = kind  # "applications" | "speakers" | "microphones"

        self.header = Label(label="", name="page-title", all_visible=True)
        self.list_box = Box(
            name="streams-list",
            orientation="vertical",
            spacing=10,
            all_visible=True,
            h_expand=True,
            v_expand=True,
        )

        self.scroller = ScrolledWindow(
            name="streams-scroll",
            child=self.list_box,
            all_visible=True,
            h_expand=True,
            v_expand=True,
            kinetic_scroll=True,
        )

        super().__init__(
            name=f"page-{kind}",
            orientation="vertical",
            spacing=10,
            all_visible=True,
            children=[self.header, self.scroller],
            h_expand=True,
            v_expand=True,
        )

        self.audio.connect("changed", lambda *_: self.rebuild())
        self.audio.connect("speaker-changed", lambda *_: self.rebuild())
        self.audio.connect("microphone-changed", lambda *_: self.rebuild())

        self.rebuild()

    def _streams(self) -> list[AudioStream]:
        if self.kind == "applications":
            return self.audio.applications
        if self.kind == "speakers":
            return self.audio.speakers
        if self.kind == "microphones":
            return self.audio.microphones
        return []

    def rebuild(self) -> None:
        if self.kind == "applications":
            self.header.set_label("Applications")  # type: ignore[attr-defined]
            rows = [StreamRow(s, show_app_id=True) for s in self._streams()]
        elif self.kind == "speakers":
            self.header.set_label("Output Devices (Sinks)")  # type: ignore[attr-defined]
            rows = [StreamRow(s) for s in self._streams()]
        else:
            self.header.set_label("Input Devices (Sources)")  # type: ignore[attr-defined]
            rows = [StreamRow(s) for s in self._streams()]

        # Replace the whole list cleanly
        self.list_box.children = rows


class OptionsPage(Box):
    def __init__(self, audio: Audio):
        self.audio = audio

        title = Label(label="Options", name="page-title", all_visible=True)
        hint = Label(
            label="(Extend this page with things like max volume, UI prefs, etc.)",
            name="options-hint",
            all_visible=True,
        )

        super().__init__(
            name="page-options",
            orientation="vertical",
            spacing=10,
            all_visible=True,
            children=[title, hint],
            h_expand=True,
            v_expand=True,
        )


class AudioControl(Box):
    def __init__(self, audio: Audio):
        self.audio = audio

        tabs = Tabs(
            tabs=[
                TabSpec("apps", "Per-App", lambda: StreamListPage(audio, "applications")),
                TabSpec("sinks", "Outputs", lambda: StreamListPage(audio, "speakers")),
                TabSpec("sources", "Inputs", lambda: StreamListPage(audio, "microphones")),
                TabSpec("opts", "Options", lambda: OptionsPage(audio)),
            ],
            default_key="apps",
        )

        super().__init__(
            name="audioctl-root",
            orientation="vertical",
            spacing=12,
            all_visible=True,
            children=[tabs],
            h_expand=True,
            v_expand=True,
            size=(900, 520),
        )