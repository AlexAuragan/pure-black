from __future__ import annotations

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.label import Label
from fabric.widgets.scale import Scale

from fabric.audio.service import AudioStream


class StreamRow(Box):
    """
    One row:
      [name/desc]  [mute]  [scale]
    """

    def __init__(self, stream: AudioStream, *, show_app_id: bool = False):
        self.stream = stream
        self._syncing = False

        title = stream.description or stream.name
        if show_app_id and stream.application_id:
            title = f"{title}  —  {stream.application_id}"

        self.label = Label(label=title, name="stream-label", all_visible=True, h_expand=True)

        self.mute_btn = Button(
            label="Mute" if not stream.muted else "Unmute",
            name="stream-mute",
            all_visible=True,
            on_clicked=self._on_toggle_mute,
        )

        self.scale = Scale(
            name="stream-scale",
            min_value=0,
            max_value=100,
            value=float(stream.volume),
            orientation="horizontal",
            all_visible=True,
            h_expand=True,
        )

        super().__init__(
            name="stream-row",
            orientation="horizontal",
            spacing=12,
            all_visible=True,
            children=[self.label, self.mute_btn, self.scale],
        )

        # Hook events
        self.scale.connect("value-changed", self._on_scale_changed)
        self.stream.connect("notify::volume", self._on_stream_volume_changed)
        self.stream.connect("notify::is-muted", self._on_stream_mute_changed)

        # Initial sync
        self._set_scale(stream.volume)
        self._set_mute_label(stream.muted)

    def _set_scale(self, vol: float) -> None:
        self._syncing = True
        self.scale.set_value(float(vol))
        self._syncing = False

    def _set_mute_label(self, muted: bool) -> None:
        # (Button has set_label in GTK; Fabric Button usually exposes it too.)
        label = "Unmute" if muted else "Mute"
        self.mute_btn.set_label(label)  # type: ignore[attr-defined]

    def _on_stream_volume_changed(self, _stream: AudioStream, _pspec) -> None:
        self._set_scale(self.stream.volume)

    def _on_stream_mute_changed(self, _stream: AudioStream, _pspec) -> None:
        self._set_mute_label(self.stream.muted)

    def _on_scale_changed(self, _scale) -> None:
        if self._syncing:
            return
        # Clamp and set
        v = float(self.scale.value)
        if v < 0:
            v = 0
        elif v > 100:
            v = 100
        self.stream.volume = v

    def _on_toggle_mute(self, _btn, *_args) -> None:
        self.stream.muted = not self.stream.muted