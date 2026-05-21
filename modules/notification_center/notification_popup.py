from __future__ import annotations

from typing import Any, Callable

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.revealer import Revealer
from fabric.widgets.scale import Scale
from fabric.widgets.wayland import WaylandWindow
from gi.repository import GdkPixbuf, GLib

from services.notifications import (
    REASON_DISMISSED,
    Notification,
    NotificationService,
)


def _pixbuf_from_hints(hints: dict) -> GdkPixbuf.Pixbuf | None:
    # image-data: (width, height, rowstride, has_alpha, bps, channels, data)
    raw = hints.get("image-data") or hints.get("image_data")
    if raw:
        try:
            width, height, rowstride, has_alpha, bps, _channels, data = raw
            return GdkPixbuf.Pixbuf.new_from_bytes(
                GLib.Bytes.new(bytes(data)),
                GdkPixbuf.Colorspace.RGB,
                has_alpha,
                bps,
                width,
                height,
                rowstride,
            )
        except Exception:
            pass

    path = hints.get("image-path") or hints.get("image_path")
    if path and isinstance(path, str):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 48, 48, True)
        except Exception:
            pass

    return None


class NotificationToast(Box):
    def __init__(self, notif: Notification, service: NotificationService, on_dismissed: Callable[..., Any]):
        self._notif = notif
        self._service = service
        self._on_dismissed = on_dismissed

        hints = notif["hints"]

        # header: app name + close button
        app_label = Label(
            name="toast-app",
            label=notif["app_name"],
            h_align="start",
            h_expand=True,
            ellipsize="end",
        )
        close_btn = Button(
            name="toast-close",
            label="✕",
            all_visible=True,
            on_clicked=self._close,
        )
        header = Box(
            name="toast-header",
            orientation="h",
            spacing=6,
            all_visible=True,
            children=[app_label, close_btn],
        )

        text_children: list[Any] = [header]

        if notif["summary"]:
            text_children.append(
                Label(
                    name="toast-summary",
                    label=notif["summary"],
                    h_align="start",
                    h_expand=True,
                    ellipsize="end",
                    all_visible=True,
                )
            )

        if notif["body"]:
            text_children.append(
                Label(
                    name="toast-body",
                    label=notif["body"],
                    h_align="start",
                    wrap=True,
                    wrap_mode="word-char",
                    all_visible=True,
                )
            )

        # progress bar (value hint 0-100)
        value = hints.get("value")
        if value is not None:
            try:
                text_children.append(
                    Scale(
                        name="toast-progress",
                        min_value=0,
                        max_value=100,
                        value=float(value),
                        orientation="horizontal",
                        h_expand=True,
                        all_visible=True,
                        sensitive=False,
                    )
                )
            except Exception:
                pass

        if notif["actions"]:
            text_children.append(self._build_actions(notif["actions"]))

        # image — album art or image-path
        pixbuf = _pixbuf_from_hints(hints)
        if pixbuf is not None:
            scaled = pixbuf.scale_simple(48, 48, GdkPixbuf.InterpType.BILINEAR)
            img = Image(name="toast-image", all_visible=True)
            img.set_from_pixbuf(scaled)
            text_col = Box(
                name="toast-text", orientation="v", spacing=4, all_visible=True, h_expand=True, children=text_children
            )
            children: list[Any] = [
                Box(name="toast-image-row", orientation="h", spacing=10, all_visible=True, children=[img, text_col])
            ]
        else:
            children = text_children

        self.revealer = Revealer(
            transition_type="slide-down",
            transition_duration=200,
            child_revealed=False,
            child=Box(
                name="toast-card",
                orientation="v",
                spacing=4,
                all_visible=True,
                h_expand=True,
                children=children,
            ),
        )

        super().__init__(
            name="toast-wrap",
            orientation="v",
            all_visible=True,
            h_expand=True,
            children=[self.revealer],
        )

    def reveal(self) -> None:
        self.revealer.set_reveal_child(True)

    def dismiss(self, then: Callable[[], Any] | None = None) -> None:
        self.revealer.set_reveal_child(False)
        GLib.timeout_add(220, lambda: (then() if then else None) or False)

    def _close(self, *_) -> None:
        self._service.close_notification(self._notif["id"], REASON_DISMISSED)

    def _build_actions(self, actions: list[str]) -> Box:
        buttons: list[Button] = []
        it = iter(actions)
        for key in it:
            label = next(it, key)
            btn = Button(
                name="toast-action-btn",
                label=label,
                all_visible=True,
                on_clicked=lambda _b, k=key: self._on_action(k),
            )
            buttons.append(btn)
        return Box(
            name="toast-actions",
            orientation="h",
            spacing=6,
            all_visible=True,
            children=buttons,
        )

    def _on_action(self, key: str) -> None:
        self._service.invoke_action(self._notif["id"], key)
        self._service.close_notification(self._notif["id"], REASON_DISMISSED)


class NotificationPopup(WaylandWindow):
    def __init__(self, service: NotificationService, **kwargs: Any):
        self._service = service
        self._toasts: dict[int, NotificationToast] = {}

        self._box = Box(
            name="toast-box",
            orientation="v",
            spacing=6,
            all_visible=True,
            h_expand=True,
        )

        super().__init__(
            layer="overlay",
            anchor="top right",
            margin="10px 10px 0px 0px",
            child=self._box,
            visible=False,
            all_visible=False,
            **kwargs,
        )

        self._service.connect("notification-added", self._on_added)
        self._service.connect("notification-closed", self._on_closed)

    def _on_added(self, _svc: NotificationService, nid: int) -> None:
        notif = self._service._by_id.get(nid)
        if notif is None:
            return

        old = self._toasts.pop(nid, None)
        if old is not None:
            self._box.remove(old)

        toast = NotificationToast(notif, self._service, on_dismissed=lambda: self._remove_toast(nid))
        self._toasts[nid] = toast

        if old is not None:
            toast.revealer.set_reveal_child(True)
            self._box.add(toast)
            toast.show_all()
        else:
            self._box.add(toast)
            if not self.get_visible():
                self.set_visible(True)
                self.show_all()
            # re-hide the dot so show_all doesn't bleed into the NC bell
            GLib.idle_add(toast.reveal)

    def _on_closed(self, _svc: NotificationService, nid: int, _reason: int) -> None:
        toast = self._toasts.get(nid)
        if toast is None:
            return
        toast.dismiss(then=lambda: self._remove_toast(nid))

    def _remove_toast(self, nid: int) -> None:
        toast = self._toasts.pop(nid, None)
        if toast is None:
            return
        self._box.remove(toast)
        if not self._toasts:
            self.set_visible(False)
