from __future__ import annotations

import time
from typing import Any

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.eventbox import EventBox
from fabric.widgets.label import Label
from fabric.widgets.scrolledwindow import ScrolledWindow
from gi.repository import Gdk

from components.popup_widget import PopupWindow
from services.notifications import (
    REASON_DISMISSED,
    Notification,
    NotificationService,
)


def _fmt_age(ts: float) -> str:
    delta = int(time.time() - ts)
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


class NotificationCard(Box):
    def __init__(self, notif: Notification, service: NotificationService):
        self._notif = notif
        self._service = service

        self.summary = Label(
            name="notif-summary",
            label=notif["summary"] or notif["app_name"],
            h_align="start",
            h_expand=True,
            ellipsize="end",
        )
        self.age = Label(
            name="notif-age",
            label=_fmt_age(notif["timestamp"]),
            h_align="end",
        )
        self.close_btn = Button(
            name="notif-close-btn",
            label="✕",
            all_visible=True,
            on_clicked=self._on_close,
        )

        header = Box(
            name="notif-header",
            orientation="h",
            spacing=6,
            all_visible=True,
            children=[self.summary, self.age, self.close_btn],
        )

        children: list[Any] = [header]

        if notif["body"]:
            self.body = Label(
                name="notif-body",
                label=notif["body"],
                h_align="start",
                wrap=True,
                wrap_mode="word-char",
                all_visible=True,
            )
            children.append(self.body)

        if notif["actions"]:
            actions_box = self._build_actions(notif["actions"])
            children.append(actions_box)

        super().__init__(
            name="notif-card",
            orientation="v",
            spacing=4,
            all_visible=True,
            h_expand=True,
            children=children,
        )
        if notif["is_permanent"]:
            self.add_style_class("notif-permanent")

    def _build_actions(self, actions: list[str]) -> Box:
        # actions is [key, label, key, label, ...]
        buttons: list[Button] = []
        it = iter(actions)
        for key in it:
            label = next(it, key)
            btn = Button(
                name="notif-action-btn",
                label=label,
                all_visible=True,
                on_clicked=lambda _b, k=key: self._on_action(k),
            )
            buttons.append(btn)
        return Box(
            name="notif-actions",
            orientation="h",
            spacing=6,
            all_visible=True,
            children=buttons,
        )

    def _on_close(self, _btn: Button) -> None:
        self._service.close_notification(self._notif["id"], REASON_DISMISSED)

    def _on_action(self, key: str) -> None:
        self._service.invoke_action(self._notif["id"], key)
        self._service.close_notification(self._notif["id"], REASON_DISMISSED)


class NotificationGroup(Box):
    def __init__(self, app_name: str, service: NotificationService):
        self._app_name = app_name
        self._service = service

        self.app_label = Label(
            name="notif-group-app",
            label=app_name,
            h_align="start",
            h_expand=True,
        )
        self.clear_btn = Button(
            name="notif-group-clear",
            label="Clear all",
            all_visible=True,
            on_clicked=self._on_clear,
        )

        self._header = Box(
            name="notif-group-header",
            orientation="h",
            spacing=6,
            all_visible=True,
            children=[self.app_label, self.clear_btn],
        )

        self._cards_box = Box(
            name="notif-group-cards",
            orientation="v",
            spacing=4,
            all_visible=True,
            h_expand=True,
        )

        super().__init__(
            name="notif-group",
            orientation="v",
            spacing=6,
            all_visible=True,
            h_expand=True,
            children=[self._header, self._cards_box],
        )

        self.rebuild()

    def rebuild(self) -> None:
        notifications = self._service.groups.get(self._app_name, [])
        cards = [NotificationCard(n, self._service) for n in reversed(notifications)]
        self._cards_box.children = cards

    def _on_clear(self, _btn: Button) -> None:
        self._service.close_group(self._app_name, REASON_DISMISSED)


class NotificationCenterView(Box):
    def __init__(self, service: NotificationService):
        self._service = service
        self._group_widgets: dict[str, NotificationGroup] = {}

        self._header = Box(
            name="notif-center-header",
            orientation="h",
            spacing=6,
            all_visible=True,
            children=[
                Label(name="notif-center-title", label="Notifications", h_expand=True, h_align="start"),
                Button(
                    name="notif-clear-all-btn",
                    label="Clear all",
                    all_visible=True,
                    on_clicked=self._on_clear_all,
                ),
            ],
        )

        self._empty_label = Label(
            name="notif-empty",
            label="No notifications",
            h_align="center",
            v_align="center",
            h_expand=True,
            v_expand=True,
            all_visible=True,
        )

        self._groups_box = Box(
            name="notif-groups",
            orientation="v",
            spacing=10,
            all_visible=True,
            h_expand=True,
        )

        self._scroller = ScrolledWindow(
            name="notif-scroller",
            child=self._groups_box,
            all_visible=True,
            h_expand=True,
            v_expand=True,
            kinetic_scroll=True,
        )

        super().__init__(
            name="notif-center-view",
            orientation="v",
            spacing=8,
            all_visible=True,
            h_expand=True,
            v_expand=True,
            size=(380, 480),
            children=[self._header, self._empty_label],
        )

        self._service.connect("notification-added", self._on_added)
        self._service.connect("notification-closed", self._on_closed)
        self._service.connect("notification-group-changed", self._on_group_changed)

        self._rebuild_all()

    # ------------------------------------------------------------------ signal handlers

    def _on_added(self, _svc: NotificationService, nid: int) -> None:
        notif = self._service._by_id.get(nid)
        if notif is None:
            return
        app = notif["app_name"]
        if app not in self._group_widgets:
            self._add_group_widget(app)
        else:
            self._group_widgets[app].rebuild()
        self._sync_empty_state()

    def _on_closed(self, _svc: NotificationService, nid: int, _reason: int) -> None:
        self._rebuild_all()

    def _on_group_changed(self, _svc: NotificationService, app_name: str) -> None:
        widget = self._group_widgets.get(app_name)
        if widget is not None:
            widget.rebuild()
        self._sync_empty_state()

    # ------------------------------------------------------------------ helpers

    def _add_group_widget(self, app_name: str) -> None:
        group = NotificationGroup(app_name, self._service)
        self._group_widgets[app_name] = group
        self._groups_box.add(group)

    def _rebuild_all(self) -> None:
        self._group_widgets.clear()
        self._groups_box.children = []
        for app_name in self._service.groups:
            self._add_group_widget(app_name)
        self._sync_empty_state()

    def _sync_empty_state(self) -> None:
        has_notifications = bool(self._service.groups)
        if has_notifications:
            if self._empty_label in self.get_children():
                self.remove(self._empty_label)
            if self._scroller not in self.get_children():
                self.add(self._scroller)
        else:
            if self._scroller in self.get_children():
                self.remove(self._scroller)
            if self._empty_label not in self.get_children():
                self.add(self._empty_label)

    def _on_clear_all(self, _btn: Button) -> None:
        for app_name in list(self._service.groups.keys()):
            self._service.close_group(app_name, REASON_DISMISSED)


class NotificationBell(Box):
    """Bar icon: bell glyph + small dot when notifications are present."""

    def __init__(self, service: NotificationService):
        self._service = service

        self._bell = Label(
            name="notif-bell-icon",
            label="notifications",
            all_visible=True,
        )
        self._dot = Label(name="notif-dot", label="●", v_align="start", h_align="center")
        self._dot.set_no_show_all(True)
        self._dot.set_visible(False)

        super().__init__(
            name="notif-bell",
            orientation="h",
            spacing=0,
            all_visible=True,
            v_align="center",
            children=[self._bell, self._dot],
        )

        self._service.connect("changed", self._on_changed)
        self._on_changed(self._service)

    def _on_changed(self, _svc: NotificationService, *_) -> None:
        has = bool(self._service.groups)
        self._dot.set_visible(has)
        if has:
            self.add_style_class("has-notifications")
        else:
            self.remove_style_class("has-notifications")


class NotificationCenter(EventBox):
    """Bar widget: click to toggle the notification panel."""

    def __init__(self, service: NotificationService, **kwargs: Any):
        self._service = service
        self._is_open = False

        self._view = NotificationCenterView(service)
        self._popup = PopupWindow(
            self._view,
            transition_type="slide-down",
            transition_duration=200,
        )

        self._bell = NotificationBell(service)

        super().__init__(
            name="notif-center",
            child=self._bell,
            events="button-press",
            **kwargs,
        )
        self.connect("button-press-event", self._on_click)
        # close when the popup loses focus (mouse leaves it)
        self._popup.connect("leave-notify-event", self._on_popup_leave)

    def _on_click(self, _widget: EventBox, event: Gdk.EventButton) -> None:
        if event.button != 1:
            return
        if self._is_open:
            self._close()
        else:
            self._open()

    def _open(self) -> None:
        self._is_open = True
        self._popup.open_under(self)

    def _close(self) -> None:
        self._is_open = False
        self._popup.close()

    def _on_popup_leave(self, _widget: Any, event: Gdk.EventCrossing) -> None:
        if event.detail == Gdk.NotifyType.INFERIOR:
            return
        self._is_open = False
