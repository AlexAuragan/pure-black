from __future__ import annotations

from typing import Any

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.label import Label
from fabric.widgets.revealer import Revealer
from fabric.widgets.wayland import WaylandWindow
from gi.repository import GLib

from services.notifications import (
    REASON_DISMISSED,
    Notification,
    NotificationService,
)


class NotificationToast(Box):
    def __init__(self, notif: Notification, service: NotificationService, on_dismissed: callable):
        self._notif = notif
        self._service = service
        self._on_dismissed = on_dismissed

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

        children: list[Any] = [header]

        if notif["summary"]:
            children.append(
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
            children.append(
                Label(
                    name="toast-body",
                    label=notif["body"],
                    h_align="start",
                    wrap=True,
                    wrap_mode="word-char",
                    all_visible=True,
                )
            )

        if notif["actions"]:
            children.append(self._build_actions(notif["actions"]))

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

    def dismiss(self, then: callable | None = None) -> None:
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

        toast = NotificationToast(notif, self._service, on_dismissed=lambda: self._remove_toast(nid))
        self._toasts[nid] = toast
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
