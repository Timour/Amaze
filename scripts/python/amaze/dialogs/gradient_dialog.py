"""The category-name dialog for the Colors section. ▸r/dialog-parents"""

from amaze.dialogs import base_dialog


class CategoryDialog(base_dialog.NameDialog):
    """The shared name input, with this section's default title."""

    def __init__(self, title: str = "Add Gradient Category", default: str = "",
                 parent=None) -> None:
        super().__init__(title, default, parent=parent)
