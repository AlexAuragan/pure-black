from fabric import Application
from fabric.widgets.wayland import WaylandWindow

from fabric.audio.service import Audio

from modules.audioctl.pages import AudioControl
from gi.repository import Gdk, Gtk


class AudioCTL:
    def __init__(self):
        self.audio = Audio(max_volume=100)

        self.root = AudioControl(self.audio)
        self.has_been_entered = False
        self.window = WaylandWindow(
            title="Fabric Audio Control",
            layer="top",
            type="top-level",
            size=(1024, 1024),
            child=self.root,
            all_visible=True,
            keyboard_mode="on-demand",
        )

        def on_enter(window: WaylandWindow, event: Gdk.Event) -> None:
            self.has_been_entered = True

        def on_key_press(window: WaylandWindow, event: Gdk.Event) -> bool:
            if event.keyval == Gdk.KEY_Escape:
                window.destroy()
                return True
            return False

        def on_focus_out(window: WaylandWindow, event: Gdk.Event) -> bool:
            if self.has_been_entered:
                window.destroy()
            return False

        self.window.connect("enter-notify-event", on_enter)
        self.window.connect("key-press-event", on_key_press)
        self.window.connect("focus-out-event", on_focus_out)
        self.window.present()


def main() -> None:
    audioctl = AudioCTL()

    app = Application("audioctl", audioctl.window)
    app.set_stylesheet_from_file("./styles/pure_black/style.css")
    app.run()


if __name__ == "__main__":
    main()
