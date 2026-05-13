from typing import Any, Callable, Literal

from fabric.widgets.eventbox import EventBox
from fabric.widgets.revealer import Revealer
from fabric.widgets.wayland import WaylandWindow
from fabric.widgets.widget import Widget
from gi.repository import Gdk, GLib

from utils.widget_utils import position_under


class PopupWindow(WaylandWindow):
    def __init__(
        self,
        child_view: Widget,
        on_before_show: Callable[[], None] | None = None,
        use_revealer: bool = True,
        transition_type: Literal[
            "none",
            "crossfade",
            "slide-right",
            "slide-left",
            "slide-up",
            "slide-down",
            # "swing-right",
            # "swing-left",
            # "swing-up",
            # "swing-down",
        ] = "slide-down",
        transition_duration: int = 250,
        **kwargs,
    ):
        self.use_revealer = use_revealer
        self.transition_duration = transition_duration
        self._hide_timer_id = None
        if self.use_revealer:
            self.revealer = Revealer(
                child=child_view,
                transition_type=transition_type,
                transition_duration=self.transition_duration,
                child_revealed=False,
            )
            content = self.revealer
        else:
            self.revealer = None
            content = child_view

        super().__init__(
            layer="overlay",
            type="popup",
            anchor="top left",
            child=content,
            visible=False,
            all_visible=False,
            **kwargs,
        )
        self.add_style_class("popup-window")
        self.on_before_show = on_before_show or (lambda *args: None)
        self.view = child_view
        self.is_hovered = False
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)

    def _on_enter(self, widget, event):
        self.is_hovered = True

    def _on_leave(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return
        self.is_hovered = False
        self.close()

    def open_under(self, parent_widget):
        if self._hide_timer_id is not None:
            GLib.source_remove(self._hide_timer_id)
            self._hide_timer_id = None
        position_under(parent_widget, self)
        if self.use_revealer:
            assert self.revealer is not None
            if not self.get_visible():
                self.set_visible(True)
                self.show_all()
            self.revealer.reveal()
        else:
            self.set_visible(True)
            self.show_all()

    def close(self):
        if self.use_revealer:
            assert self.revealer is not None
            self.revealer.unreveal()
            if self._hide_timer_id is not None:
                GLib.source_remove(self._hide_timer_id)
            self._hide_timer_id = GLib.timeout_add(
                self.transition_duration, self._hide_window
            )
        else:
            self._hide_window()

    def _hide_window(self):
        self.set_visible(False)
        self._hide_timer_id = None
        return False


class PopupWidget(EventBox):
    def __init__(
        self,
        main_widget: Widget,
        popup_window: PopupWindow,
        interactive: bool = False,
        **kwargs,
    ):
        super().__init__(child=main_widget, **kwargs)
        self.popup = popup_window
        self.interactive = interactive
        self._close_timer = None

        # Connect Hover Events
        self.connect("enter-notify-event", self._on_hover_enter)
        self.connect("leave-notify-event", self._on_hover_exit)

    def _on_hover_enter(self, widget, event):
        if self._close_timer:
            GLib.source_remove(self._close_timer)
            self._close_timer = None

        if self.popup._hide_timer_id is not None:
            GLib.source_remove(self.popup._hide_timer_id)
            self.popup._hide_timer_id = None

        self.popup.on_before_show()
        self.popup.open_under(self)

    def _on_hover_exit(self, widget, event):
        # Prevent flickering when moving mouse from widget into the popup itself
        if event.detail == Gdk.NotifyType.INFERIOR:
            return
        if self.interactive:
            self._close_timer = GLib.timeout_add(100, self._check_should_close)
        else:
            self.popup.close()

    def _check_should_close(self):
        if not self.popup.is_hovered:
            self.popup.close()
        self._close_timer = None
        return False  # Do not repeat the timer
