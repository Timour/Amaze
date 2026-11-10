"""The tile capture: the Scene View as a tile's picture, for one panel."""

import hou

from amaze import messages
from amaze.core import debug, scene_captures


class TileCapture:
    """One panel's Capture doors; the panel holds it as `tile_capture`."""

    def __init__(self, panel) -> None:
        self.panel = panel

    def from_toolbar(self) -> None:
        """Toolbar Capture: the one selected tile; in File with nothing selected, the open scene."""
        context = self.panel.active_section()
        indexes = context.grid_selection() if context is not None else []
        if len(indexes) == 1 and getattr(context, "takes_capture", False):
            self.onto_tile(context, indexes[0])
        elif not indexes and getattr(context, "key", "") == "file":
            self.capture_and_report()    # "" = the scene the viewport is showing
        else:
            self.report_refused(messages.CAPTURE_SELECT_ONE_TILE)

    def onto_tile(self, context, proxy_index) -> None:
        """The Scene View as one tile's picture, the tile then showing it. Never automatic ▸r/tile-captures"""
        model, proxy = context.tile_models()
        if model is None or proxy_index is None or not proxy_index.isValid():
            return
        source = proxy.mapToSource(proxy_index) if proxy is not None else proxy_index
        row = source.row()
        scene = self.panel.hip_path_for(proxy_index) if getattr(context, "key", "") == "file" else ""
        if scene:
            captured = self.capture_and_report(scene)    # a scene only while it is the one open
        else:
            captured = self.run(
                lambda: scene_captures.capture_tile(model.capture_path(row), model.tile_key(row)),
                model.tile_key(row))
        if captured:
            self.panel.apply_icon_spec(model, [row], {"face": "capture"})

    def capture_and_report(self, target: str = "") -> bool:
        """The open scene onto its File tile; "" means whatever is open. Answers whether it landed."""
        return self.run(
            lambda: scene_captures.capture_open_scene(self.panel.prefs, target), target)

    def run(self, capture, label: str) -> bool:
        """Run one capture and SAY WHY it refused: a silent refusal reads as a broken feature."""
        try:
            capture()
        except scene_captures.CaptureRefused as exc:
            debug.event("hip", "capture refused", file=label, reason=str(exc))
            self.report_refused(str(exc))
            return False
        return True

    def report_refused(self, text: str) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(text, title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
