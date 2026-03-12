import datetime
import faulthandler
import math
import sys
import threading
import time

from fabric.widgets.box import Box
from fabric.widgets.eventbox import EventBox
from fabric.widgets.image import Image
from fabric.widgets.label import Label
from fabric.widgets.overlay import Overlay
from fabric.widgets.stack import Stack

from gi.repository import Gdk, GLib
from gi.repository.GdkPixbuf import Pixbuf
from gi.repository.Gtk import Align

from config.names import WORKSPACE_LABELS
from services.hyprland import HyprlandManager, Monitor

from fabric.widgets.shapes import Corner

from services.watchdog import watchdog


class WorkspaceIndicator(Box):
    """
    A single moving dot (a Box styled as a circle) that animates between positions.
    Place it in an overlay above your icons, top-left aligned, and move it by setting margins.
    """

    def __init__(self, diameter: int, duration_ms: int, ws_tray: "HyprlandWorkspacesTray", **kwargs):
        super().__init__(**kwargs)
        self.ws_id = None
        self.ws_tray = ws_tray
        self.base_d = int(diameter)
        self.duration_ms = int(duration_ms)
        self._segments: list[tuple[float, float, str, float]] = []
        self._axis = "x"
        self._seg_duration_ms = float(self.duration_ms)

        self.add_style_class("workspace-indicator")
        self.add_style_class("hidden")
        # current center position (in overlay coords)
        self.cx = 0.0
        self.cy = 0.0

        # animation state
        self._anim_source_id: int | None = None
        self._t0 = 0.0
        self._sx = 0.0
        self._sy = 0.0
        self._tx = 0.0
        self._ty = 0.0

        # initial size
        self.set_size_request(self.base_d, self.base_d)

        self.set_halign(Align.START)
        self.set_valign(Align.START)

    def animate_to(self, x: float, y: float):
        x = float(x)
        y = float(y)

        # show only while animating
        if self.ws_id is not None:
            self.remove_style_class("hidden")

        # stop current animation
        if self._anim_source_id is not None:
            GLib.Source.remove(self._anim_source_id)
            self._anim_source_id = None


        # displacement
        dx = x - self.cx
        dy = y - self.cy

        self._segments.clear()

        # Two-step if moving in both dimensions
        if dx and dy:
            # X then Y (swap these two lines if you want Y then X)
            seg1_dist = abs(dx)
            seg2_dist = abs(dy)
            total = seg1_dist + seg2_dist

            # Split total duration proportionally
            d1 = max(1.0, self.duration_ms * (seg1_dist / total))
            d2 = max(1.0, self.duration_ms * (seg2_dist / total))

            self._segments.append((x, self.cy, "x", d1))
            self._segments.append((x, y, "y", d2))
        else:
            axis = "x" if abs(dx) >= abs(dy) else "y"
            self._segments.append((x, y, axis, float(self.duration_ms)))

        self._start_next_segment()

    def _tick(self) -> bool:
        now = time.monotonic()
        elapsed_ms = (now - self._t0) * 1000.0
        t = elapsed_ms / self._seg_duration_ms

        if t >= 1.0:
            self.cx, self.cy = self._tx, self._ty
            self._apply_geometry(self.cx, self.cy, stretch=0.0, axis=self._axis)
            self._anim_source_id = None

            # start next segment (if any)
            self._start_next_segment()
            return False

        # ease out cubic
        p = 1 - (1 - t) ** 3

        dx = self._tx - self._sx
        dy = self._ty - self._sy
        cx = self._sx + dx * p
        cy = self._sy + dy * p
        self.cx, self.cy = cx, cy

        dist = math.hypot(dx, dy)
        dist_norm = min(1.0, dist / 120.0)
        pulse = math.sin(math.pi * p)
        stretch = dist_norm * pulse

        self._apply_geometry(cx, cy, stretch=stretch, axis=self._axis)
        return True

    def _start_next_segment(self):
        if not self._segments:
            # nothing left -> fully done
            self.add_style_class("hidden")
            self.ws_tray.set_active_class(self.ws_id)
            return

        tx, ty, axis, dur_ms = self._segments.pop(0)

        self._t0 = time.monotonic()
        self._sx, self._sy = self.cx, self.cy
        self._tx, self._ty = tx, ty
        self._axis = axis
        self._seg_duration_ms = max(1.0, float(dur_ms))

        self._anim_source_id = GLib.timeout_add(16, self._tick)


    def _apply_geometry(self, cx: float, cy: float, stretch: float, axis: str):
        # stretch the blob along the travel axis and slightly squash perpendicular
        d = float(self.base_d)

        if axis == "x":
            w = d * (1.0 + stretch)
            h = d * (1.0 - 0.45 * stretch)
        else:
            w = d * (1.0 - 0.45 * stretch)
            h = d * (1.0 + stretch)

        w_i = max(2, int(round(w)))
        h_i = max(2, int(round(h)))
        self.set_size_request(w_i, h_i)

        # position by margins so that the widget stays centered at (cx, cy)
        left = int(round(cx - w_i / 2))
        top = int(round(cy - h_i / 2))

        # use the parents to avoid stretching outside the allocated area
        parent = self.get_parent()
        if parent is not None:
            palloc = parent.get_allocation()
            left = max(0, min(left, max(0, palloc.width - w_i)))
            top = max(0, min(top, max(0, palloc.height - h_i)))

        self.set_margin_start(left)
        self.set_margin_top(top)

class HyprlandWorkspaceIcon(EventBox):
    def __init__(self, idx: int, hyprland: HyprlandManager, monitor_id: int, **kwargs):
        self.id = idx
        self._monitor_id = monitor_id
        self.hyprland = hyprland
        self.app_icons: dict[str, str] = {}
        self._pixbuf_cache: dict[str, Pixbuf] = {}
        self.last_client_address = self.hyprland.workspaces.get(self.id, {}).get("last_window") or ""

        self.image = Image(**kwargs)
        self.label = Label(label=WORKSPACE_LABELS.get(idx, WORKSPACE_LABELS[0]), style_classes="workspace_label")
        self.content = Stack(children=[self.image, self.label])
        self.content.set_visible_child(self.label)

        super().__init__(
            child=self.content,
            events=["button-press", "enter-notify", "leave-notify"], # type:ignore
        )
        self.add_style_class("workspace-button-box")
        self.add_style_class("inactive")

        self.connect("button-press-event", self.on_button_press)
        self.connect("enter-notify-event", self.on_hover_enter)
        self.connect("leave-notify-event", self.on_hover_exit)

        self._on_workspace_icons_notify(hyprland, self.id)
        self.hyprland.connect("workspace-icons-changed", self._on_workspace_icons_notify)

    def _on_workspace_icons_notify(self, hyprland: HyprlandManager, workspace_id: int):
        if workspace_id != self.id:
            return
        if not hyprland.workspace_icons.get(self.id):
            return
        icon_pixbuf = hyprland.workspace_icons[self.id]["icon_pixbuf"]
        if icon_pixbuf is None:
            self.content.set_visible_child(self.label)
            self.add_style_class("empty")
            return
        self.image.set_from_pixbuf(icon_pixbuf)
        self.content.set_visible_child(self.image)
        self.remove_style_class("empty")

    def on_button_press(self, widget: "HyprlandWorkspaceIcon", event):
        if event.button == 1:
            widget.on_left_click()
        return True

    def on_left_click(self, *_):
        self.hyprland.focus_workspace_current_monitor(self.id)

    def on_hover_exit(self, widget, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            # Ignore leaving into a child widget
            return
        self.remove_style_class("hover")

    def on_hover_enter(self, *_):
        self.add_style_class("hover")

    @property
    def monitor_id(self):
        return self._monitor_id

class HyprlandWorkspaceDummyIcon(EventBox):
    def __init__(self):
        self.label = Label(label=WORKSPACE_LABELS[0], style_classes="workspace_label")
        self.image = Image()
        self.content = Stack(children=[self.image, self.label])
        super().__init__(
            child=self.content
        )
        self.add_style_class("workspace-button-box")
        self.add_style_class("workspace-color-indicator")


class HyprlandWorkspacesTray(Overlay):
    def __init__(self, hyprland: HyprlandManager, monitor_id: int, two_rows=True, **kwargs):
        self.hyprland = hyprland
        self._monitor_id = monitor_id
        # n = max(self.hyprland.workspaces.keys())
        n = 10
        # TODO add the management of dynamic workspaces 
        self.icons: dict[int, HyprlandWorkspaceIcon] = {}

        if two_rows:
            first_row = Box(
                children=[self.make_icon(i) for i in range(1, (n+1)//2 + 1)],
                style_classes=["workspace-row"],
                spacing=2,
            )
            second_row = Box(
                children=[self.make_icon(i) for i in range((n+1)//2 + 1, n + 1)],
                style_classes=["workspace-row"],
                spacing=2,
            )
            dummy_first_row = Box(
                children=[HyprlandWorkspaceDummyIcon() for i in range(1, (n+1)//2 + 1)],
                style_classes=["workspace-row"],
                spacing=2,
            )
            dummy_second_row = Box(
                children=[HyprlandWorkspaceDummyIcon() for i in range((n+1)//2 + 1, n + 1)],
                style_classes=["workspace-row"],
                spacing=2,
            )
            content = Box(children=[first_row, second_row], orientation="v", spacing=2, css_name="workspace")
            content_background = Box(children=[dummy_first_row, dummy_second_row], orientation="v", spacing=2, css_name="workspace")
        else:
            content = Box(
                children=[self.make_icon(i) for i in range(1, n + 1)],
                style_classes=["workspace-row"],
                css_name="workspace",
                spacing=2,
            )
            content_background = Box(
                children=[HyprlandWorkspaceDummyIcon() for i in range(1, n + 1)],
                style_classes=["workspace-row"],
                css_name="workspace",
                spacing=2,
            )


        left_corner = Corner(
            orientation="top-right", size=12, style_classes=["shape", "top-corner"],
            v_align="start", v_expand=False # Needed to hide the overflow of the shape next to a rounded corner
        )
        right_corner = Corner(
            orientation="top-left", size=12, style_classes=["shape", "top-corner"],
            v_align="start", v_expand=False
        )
        left_cornerh = Corner(orientation="top-right", size=12, style_classes=["hidden"]) # Same corners but hidden
        right_cornerh = Corner(orientation="top-left", size=12, style_classes=["hidden"])
        self.indicator = WorkspaceIndicator(diameter=20, duration_ms=360, ws_tray = self)
        content.set_name("workspaces-content")
        content_background.set_name("workspaces-background")
        super().__init__(
            child=Box(children=[left_corner, content_background, right_corner], orientation="h"),
            overlays=[self.indicator, Box(children=[left_cornerh, content, right_cornerh])],
            **kwargs,
        )
        self.add_style_class("top-widget")
        self.set_name("workspaces")

        self.hyprland.connect("notify::monitors", self._on_monitors)
        self._place_initial_indicator()
        GLib.timeout_add(50, self._heartbeat)  # 20 Hz

    def _heartbeat(self):
        watchdog.beat()
        return True


    def make_icon(self, i: int) -> HyprlandWorkspaceIcon:
        icon = HyprlandWorkspaceIcon(i, self.hyprland, monitor_id=self.monitor_id)
        self.icons[i] = icon
        return icon

    @property
    def monitor_id(self):
        return self._monitor_id

    def _place_initial_indicator(self):
        monitors = self.hyprland.monitors
        if not monitors:
            return False

        mon = monitors[self.monitor_id]
        ws_id = int(mon["active_workspace_id"])

        self.set_active_class(ws_id)
        return False

    def _on_monitors(self, hyprland: HyprlandManager, event):
        mon_id = self.monitor_id
        mon = hyprland.monitors.get(mon_id)
        if not mon:
            return

        self._pending_ws_id = mon["active_workspace_id"]

        if self._pending_ws_id == self.indicator.ws_id:
            return

        self.indicator.ws_id = self._pending_ws_id
        self._pending_move_source_id = GLib.timeout_add(0, self._run_pending_move)

    def set_active_class(self, ws_id: int | None):
        for i, icon in self.icons.items():
            if i == ws_id:
                icon.add_style_class("active")
            else:
                icon.remove_style_class("active")

    def _move_indicator_to_workspace(self, ws_id: int):
        self.set_active_class(None)
        icon = self.icons.get(ws_id)
        if icon is None:
            return False

        # Center relative to icon itself:
        alloc = icon.get_allocation()

        local_x = alloc.width / 2
        local_y = alloc.height / 2

        # Translate to overlay coords
        x, y = icon.translate_coordinates(self, int(local_x), int(local_y))

        self.indicator.ws_tray = self
        self.indicator.ws_id = ws_id
        self.indicator.animate_to(x, y)

    def _run_pending_move(self):
        self._pending_move_source_id = None
        ws_id = self._pending_ws_id
        self._pending_ws_id = None
        if ws_id is None:
            return False

        self._move_indicator_to_workspace(ws_id)
        return False