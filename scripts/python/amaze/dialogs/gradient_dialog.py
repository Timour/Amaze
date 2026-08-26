"""Save dialog for gradients, and the minimal category-name dialog - both AssetDialog subclasses, so the house form style lives in `dialogs/base_dialog.py`. ▸r/dialog-parents"""

from amaze import amazetheme
from amaze import branding
from amaze.dialogs import base_dialog
from amaze.dialogs.base_dialog import AssetDialog


class GradientDialog(AssetDialog):

    FORM_WIDTH = base_dialog.SAVE_WIDTH
    FIELD_WIDTH = amazetheme.SAVE_FIELD_WIDTH

    def __init__(self, categories: list, default_name: str = "",
                 parent=None) -> None:
        super().__init__("Save Gradient to " + branding.APP_NAME,
                         parent=parent)
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



class CategoryDialog(base_dialog.NameDialog):
    """The shared name input, with this section's default title - the body lives in `base_dialog.NameDialog`."""

    def __init__(self, title: str = "Add Gradient Category",
                 parent=None) -> None:
        super().__init__(title, parent=parent)
