from fabric.widgets.wayland import WaylandWindow
from fabric.widgets.widget import Widget
from gi.repository import Gdk


def position_under(widget: Widget, popup: WaylandWindow, gap: int = 4) -> None:
    # widget allocation (relative to its toplevel)
    alloc = widget.get_allocation()

    toplevel = widget.get_toplevel()
    win = toplevel.get_window()
    if win is None:
        return

    # absolute position of the toplevel window
    ok, wx, wy = win.get_origin()

    # widget absolute x position + center
    widget_center_x = wx + alloc.x + (alloc.width // 2)

    popup_w = popup.get_allocated_width()
    if popup_w <= 1:
        popup_w = popup.get_preferred_size()[1].width

    left = max(0, widget_center_x - (popup_w // 2))
    popup.margin = f"{gap}px 0px 0px {left}px"
