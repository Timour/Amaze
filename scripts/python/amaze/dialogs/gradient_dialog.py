"""
Save dialog for gradients ("Save Gradient to Amaze" on a node with a
color ramp) and the minimal category-name dialog. Both are AssetDialog
subclasses - the house form style (right-aligned labels, 5px margins,
content-hugging fixed size, OK/Cancel) lives in dialogs/base_dialog.py.
"""

from amaze import branding
from amaze.dialogs.base_dialog import AssetDialog


class GradientDialog(AssetDialog):
    def __init__(self, categories: list, default_name: str = "") -> None:
        super().__init__("Save Gradient to " + branding.APP_NAME)
        self.name = ""
        self.category = ""

        self._line_name = self.add_line("Name", default_name)
        self._combo_category = self.add_combo(
            "Category",
            categories,
            current=categories[0] if categories else "",
            editable=True,
        )
        self.finish()

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        self.category = self._combo_category.currentText().strip()
        super()._on_accept()



class CategoryDialog(AssetDialog):
    """Minimal name-input dialog - replaces hou.ui.readInput, whose
    native dialog carries an unwanted "i" icon and separator lines."""

    def __init__(self, title: str = "Add Gradient Category") -> None:
        super().__init__(title)
        self.name = ""
        self._line_name = self.add_line("Name")
        self.finish()

    def _on_accept(self) -> None:
        self.name = self._line_name.text().strip()
        super()._on_accept()
