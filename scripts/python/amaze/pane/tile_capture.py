"""The tile capture: the Scene View as a tile's picture, for one pane."""

import hou

from amaze import messages
from amaze.core import debug, library_db, scene_captures


class TileCapture:
    """One pane's Capture commands; the pane holds it as `tile_capture`."""

    def __init__(self, pane) -> None:
        self.pane = pane

    def onto_tile(self, context, proxy_index) -> None:
        """The Scene View as one tile's picture, the tile then showing it. Never automatic ▸r/tile-captures"""
        model, proxy = context.tile_models()
        if model is None or proxy_index is None or not proxy_index.isValid():
            return
        source = proxy.mapToSource(proxy_index) if proxy is not None else proxy_index
        row = source.row()
        scene = self.pane.files.hip_path_for(proxy_index) if getattr(context, "key", "") == "file" else ""
        if scene:
            captured = self.capture_and_report(scene)    # raises CaptureRefused unless `scene` is open
        else:
            captured = self.run(
                lambda: scene_captures.capture_tile(
                    model.capture_path(row), model.tile_key(row),
                    library_db.user(model.preferences)),
                model.tile_key(row))
        if captured:
            self.pane.assets.apply_icon_spec(model, [row], {"face": "image"})

    def capture_and_report(self, target: str = "") -> bool:
        """Capture the open scene onto its File tile; `""` means the open one. True if it worked."""
        return self.run(
            lambda: scene_captures.capture_open_scene(self.pane.prefs, target), target)

    def run(self, capture, label: str) -> bool:
        """Run one capture and show why it failed: a silent failure looks like a bug."""
        try:
            capture()
        except scene_captures.CaptureRefused as exc:
            debug.event("hip", "capture failed", file=label, reason=str(exc))
            self.show_capture_warning(str(exc))
            return False
        return True

    def show_capture_warning(self, text: str) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(text, title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
