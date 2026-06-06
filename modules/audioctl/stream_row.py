from __future__ import annotations

from typing import Any

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.label import Label
from fabric.widgets.scale import Scale

from fabric.audio.service import AudioStream


class StreamRow(Box):
    """One row: [name (fixed 220px)] [━━━━●━━━━ scale] [Mute]"""

    def __init__(self, stream: AudioStream, *, show_app_id: bool = False):
        self.stream = stream
        self._syncing = False

        title = stream.description or stream.name
        if show_app_id and stream.application_id:
            title = f"{title}  —  {stream.application_id}"

        self.label = Label(
            label=title,
            name="stream-label",
            all_visible=True,
            ellipsization="end",
            justification="left",
            max_chars_width=30,
            h_expand=True,
            v_align="center",
            h_align="start",
        )

        self.label_box = Box(
            name="stream-label-box",
            all_visible=True,
            h_expand=False,
            v_align="center",
            size=(220, -1),
            children=[self.label],
        )

        self.scale = Scale(
            name="stream-scale",
            min_value=0,
            max_value=100,
            value=float(stream.volume),
            orientation="horizontal",
            all_visible=True,
            h_expand=True,
            v_align="center",
        )

        self.scale_box = Box(
            name="stream-scale-box",
            all_visible=True,
            h_expand=True,
            v_align="center",
            children=[self.scale],
        )

        self.mute_btn = Button(
            label="Unmute" if stream.muted else "Mute",
            name="stream-mute",
            all_visible=True,
            on_clicked=self._on_toggle_mute,
            v_align="center",
            h_align="center",
        )

        self.mute_box = Box(
            name="stream-mute-box",
            all_visible=True,
            h_expand=False,
            v_align="center",
            size=(80, -1),
            children=[self.mute_btn],
        )

        super().__init__(
            name="stream-row",
            orientation="horizontal",
            spacing=12,
            all_visible=True,
            children=[self.label_box, self.scale_box, self.mute_box],
        )

        # Scale → audio service
        self.scale.connect("value-changed", self._on_scale_changed)

        # Audio service → UI (covers volume, mute, and any external change)
        self.stream.connect("changed", self._on_stream_changed)

        self._sync_from_stream()

    def _sync_from_stream(self) -> None:
        self._syncing = True
        self.scale.set_value(float(self.stream.volume))
        self.mute_btn.set_label("Unmute" if self.stream.muted else "Mute")
        self._syncing = False

    def _on_stream_changed(self, *_: Any) -> None:
        self._sync_from_stream()

    def _on_scale_changed(self, _scale: Scale) -> None:
        if self._syncing:
            return
        self.stream.volume = max(0.0, min(100.0, float(self.scale.value)))

    def _on_toggle_mute(self, _btn: Button, *_: Any) -> None:
        self.stream.muted = not self.stream.muted
