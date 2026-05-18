from dataclasses import dataclass
from typing import Callable

from fabric.widgets.box import Box
from fabric.widgets.button import Button
from fabric.widgets.eventbox import EventBox
from fabric.widgets.shapes import Corner
from fabric.widgets.stack import Stack
from gi.repository import Gdk, Gtk


@dataclass(frozen=True)
class TabSpec:
    key: str
    title: str
    page_factory: Callable[[], object]  # returns a Widget


class FolderTab(Box):
    """
    A single tab "folder" button:
      [left corner][button area][right corner]
    """

    def __init__(self, title: str, on_click: Callable[[Button], None]):
        self.on_click = on_click
        self.left = Corner(
            orientation="bottom-right",
            size=12,
            style_classes=["shape", "tab-corner", "tab-left-corner"],
            v_align="end",
            v_expand=False,
        )
        self.right = Corner(
            orientation="bottom-left",
            size=12,
            style_classes=["shape", "tab-corner", "tab-right-corner"],
            v_align="end",
            v_expand=False,
        )

        self.button = Button(
            label=title,
            name="tab-button",
            style_classes=["tab-button-core"],
            all_visible=True,
            on_clicked=on_click,
            # Make the button itself focusable, so you get visual focus per tab
            can_focus=True,
        )

        self.core = Box(
            name="tab-core",
            style_classes=["tab-core"],
            children=[self.button],
            all_visible=True,
            v_align="start",
        )

        super().__init__(
            name="folder-tab",
            style_classes=["folder-tab"],
            orientation="horizontal",
            spacing=0,
            children=[self.left, self.core, self.right],
            all_visible=True,
            v_align="start",
            v_expand=False,
        )

    def set_active(self, active: bool) -> None:
        if active:
            self.add_style_class("active")
        else:
            self.remove_style_class("active")

    def focus(self) -> None:
        # Give keyboard focus to the button inside the tab
        self.button.grab_focus()


class Tabs(EventBox):
    """
    Folder-like tabs with keyboard navigation:
      - Tab / Shift+Tab moves focus between tabs
      - Enter / Space activates focused tab
    """

    def __init__(self, tabs: list[TabSpec], default_key: str):
        self._tabs = tabs
        self._tab_widgets: dict[str, FolderTab] = {}
        self._key_order: list[str] = [spec.key for spec in tabs]
        self._current_key: str | None = None

        self._tab_bar = Box(
            name="tabs-bar",
            style_classes=["tabs-bar"],
            orientation="horizontal",
            spacing=0,
            all_visible=True,
            v_align="start",
            v_expand=False,
        )

        self._stack = Stack(
            name="tabs-stack",
            transition_type="crossfade",
            transition_duration=160,
            children=[],
            all_visible=True,
            v_expand=True,
            h_expand=True,
        )

        self._content_bg = Box(
            name="tabs-content-bg",
            style_classes=["content-background"],
            orientation="vertical",
            children=[self._stack],
            all_visible=True,
            h_expand=True,
            v_expand=True,
        )

        super().__init__(
            name="tabs-root",
            style_classes=["tabs-root"],
            child=Box(
                children=[self._tab_bar, self._content_bg],
                orientation="vertical",
                spacing=0,
            ),
            all_visible=True,
            h_expand=True,
            v_expand=True,
            can_focus=True,
            events="key-press",
        )

        self._build(default_key)
        self.connect("key-press-event", self._on_key_pressed)

    def _build(self, default_key: str) -> None:
        # pages
        for spec in self._tabs:
            page = spec.page_factory()
            self._stack.add_named(page, spec.key)  # type: ignore[attr-defined]

        # tab buttons
        bar_children: list[FolderTab] = []
        for spec in self._tabs:
            key = spec.key

            def make_handler(tab_key: str):
                def handler(_btn: Button) -> None:
                    self.set_current(tab_key)

                return handler

            tab = FolderTab(
                spec.title,
                on_click=make_handler(key),
            )
            self._tab_widgets[key] = tab
            bar_children.append(tab)

        self._tab_bar.children = bar_children
        self.set_current(default_key)
        # Initial keyboard focus on the active tab
        self._focus_current_tab()

    def _focus_current_tab(self) -> None:
        if self._current_key is None:
            return
        tab = self._tab_widgets.get(self._current_key)
        if tab is not None:
            tab.focus()

    def _on_key_pressed(self, widget: Gtk.Widget, event: Gdk.Event) -> bool:
        """
        Handle Tab / Shift+Tab to move across tabs.
        Optionally handle Enter/Space to activate the focused tab again.
        """
        keyval = event.keyval
        if keyval == Gdk.KEY_Tab:
            self._focus_next_tab()
        elif keyval == Gdk.KEY_ISO_Left_Tab:
            self._focus_prev_tab()

        return False  # let other handlers run

    def _focus_next_tab(self) -> None:
        if self._current_key is None:
            return

        curr = self._key_order.index(self._current_key)
        nxt = (curr + 1) % len(self._key_order)
        self.set_current(self._key_order[nxt])

    def _focus_prev_tab(self) -> None:
        if self._current_key is None:
            return

        curr = self._key_order.index(self._current_key)
        prev = (curr - 1) % len(self._key_order)
        self.set_current(self._key_order[prev])

    def set_current(self, key: str) -> None:
        self._stack.set_visible_child_name(key)  # type: ignore[attr-defined]
        self._current_key = key
        for k, tab in self._tab_widgets.items():
            tab.set_active(k == key)
        # Also update keyboard focus to the active tab
        self._focus_current_tab()
