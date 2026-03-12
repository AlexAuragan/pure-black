def position_under(widget, popup, gap=4):
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
    if popup_w <= 1: # On first init, the first popup_w can be 0 or 1, we try something else to fetch the width of the
        # widget
        popup_w = popup.get_preferred_size()[1].width

    # ensure popup has a size (needs to be realized/shown at least once)
    left = max(0, widget_center_x - (popup_w // 2))
    popup.set_margin(f"{gap}px 0px 0px {left}px")
