from fabric.widgets.box import Box
from fabric.widgets.label import Label
from fabric.audio.service import Audio

from config.names import WORKSPACE_LABELS
from services.hyprland import HyprlandManager, ActiveWindow, Monitor


def shorten_title(string: str):
    max_len = 50
    if string.count("/") >= 4:
        split = string.split("/")
        return ("/".join(split[:2])) + "/.../" + ("/".join(split[-2:]))

    if len(string) > max_len:
        split = string.split(" ")
        out = ""
        i = 0
        while len(out + split[i]) <= max_len:
            out += " " + split[i]
            i += 1
        return out + "..."

    return string


class ActiveWindowWidget(Box):
    def __init__(self, hypr: HyprlandManager, mon_id: int, **kwargs):
        self.hypr = hypr
        self.mon_id = mon_id

        self.test_audio = Audio()

        _ws_id = self.hypr.workspaces[self.mon_id]["id"] if self.mon_id in self.hypr.workspaces else None
        icon_id: int | None = int(_ws_id) if _ws_id is not None else None
        self.icon = Label(
            name="active_workspace_label",
            label=WORKSPACE_LABELS.get(icon_id, "~") if icon_id is not None else "~",
        )
        self.class_ = Label(
            name="active_window_class",
            label="~",
            h_align="start",
            style="font-size:8px;",
        )
        self.title = Label(
            name="active_window_title",
            label="~",
            h_align="fill",
            style="font-size:14px;",
        )
        self.icon.add_style_class("active_window_icon")
        super().__init__(
            name="active-window",
            orientation="h",
            spacing=4,
            children=[self.icon, self.title],
            **kwargs,
        )
        self.add_style_class("top-widget")

        self.hypr.connect("notify::active-windows", self.on_active_window_change)
        self.hypr.connect("notify::monitors", self.on_monitor_change)

    def on_active_window_change(self, hypr: HyprlandManager):
        active_window: ActiveWindow | None = hypr.active_windows.get(self.mon_id)

        if active_window is None:
            self.class_.set_label("")
            self.title.set_label("")
            return

        # self.class_.set_label(active_window["class_"] or "")
        self.title.set_label(shorten_title(active_window["title"]) or "")

    def on_monitor_change(self, hypr: HyprlandManager):
        monitor: Monitor | None = hypr.monitors.get(self.mon_id)
        if monitor is None:
            return

        self.icon.set_label(WORKSPACE_LABELS[monitor["active_workspace_id"]])
