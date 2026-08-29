"""The minimal category-name dialog for the Colors section - an AssetDialog subclass, so the house form style lives in `dialogs/base_dialog.py`. ▸r/dialog-parents"""

from amaze.dialogs import base_dialog


class CategoryDialog(base_dialog.NameDialog):
    """The shared name input, with this section's default title - the body lives in `base_dialog.NameDialog`."""

    def __init__(self, title: str = "Add Gradient Category",
                 parent=None) -> None:
        super().__init__(title, parent=parent)
