from os import PathLike
from pathlib import Path
from typing import Any, Literal, Iterable

from gi.overrides.Gtk import Gtk
from gi.repository import Rsvg
import cairo
from fabric.widgets.svg import Svg as FabricSvg
from loguru import logger


class Svg(FabricSvg):
    """
    Adds dynamic `color` support sourced from `Gtk.StyleContext`.
    """

    def __init__(
        self,
        svg_file: str | Path | None = None,
        size: Iterable[int] | int | None = 12,
        svg_string: str | None = None,
        name: str | None = None,
        visible: bool = True,
        all_visible: bool = False,
        style: str | None = None,
        style_classes: Iterable[str] | str | None = None,
        tooltip_text: str | None = None,
        tooltip_markup: str | None = None,
        h_align: Literal["fill", "start", "end", "center", "baseline"] | Gtk.Align | None = None,
        v_align: Literal["fill", "start", "end", "center", "baseline"] | Gtk.Align | None = None,
        h_expand: bool = False,
        v_expand: bool = False,
        **kwargs: Any,
    ):
        if isinstance(svg_file, Path):
            svg_file = str(svg_file)

        super().__init__(
            svg_file=svg_file,
            svg_string=svg_string,
            name=name,
            visible=visible,
            all_visible=all_visible,
            style=style,
            style_classes=style_classes,
            tooltip_text=tooltip_text,
            tooltip_markup=tooltip_markup,
            h_align=h_align,
            v_align=v_align,
            h_expand=h_expand,
            v_expand=v_expand,
            size=size,
            **kwargs,
        )

    def do_draw(self, cr: cairo.Context):
        if not self._handle:
            return

        context = self.get_style_context()
        state = context.get_state()
        color = context.get_color(state)

        bridge_css = f"""
            * {{ 
                color: rgba({int(color.red * 255)}, {int(color.green * 255)}, {int(color.blue * 255)}, {color.alpha})
            }}
        """

        if self._style_compiled:
            final_style = bridge_css + self._style_compiled
        else:
            final_style = bridge_css

        if not self._handle.set_stylesheet(final_style.encode()):
            logger.error("[Svg] Failed to apply styles, probably invalid style property")

        alloc = self.get_allocation()
        width: int = alloc.width  # type: ignore
        height: int = alloc.height  # type: ignore

        rect = Rsvg.Rectangle()
        rect.x = rect.y = 0
        rect.width = width  # type: ignore
        rect.height = height  # type: ignore

        cr.save()
        self._handle.render_document(cr, rect)
        cr.restore()
