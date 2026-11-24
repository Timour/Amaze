"""A library switch repoints every library-backed model of the pane engine. ▸p/area-bindings"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze.tests import test_support  # noqa: E402


class EveryLibraryBackedModelIsDeclaredBySection(unittest.TestCase):
    """Models a library switch repoints are derived from the sections; asserted in both directions."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @staticmethod
    def _declared():
        from amaze import sections
        declared = set()
        for section_cls in sections.SECTION_CLASSES:
            declared.update(getattr(section_cls, "library_model_attrs", ()))
        return declared

    def test_every_declared_attribute_exists_and_can_switch(self):
        declared = self._declared()
        self.assertTrue(declared, "no section declares a library model")
        broken = {}
        for attr in sorted(declared):
            model = getattr(self.panel.pane, attr, None)
            if model is None:
                broken[attr] = "not built on the pane"
            elif not callable(getattr(model, "switch_model_data", None)):
                broken[attr] = "%s has no switch_model_data" % type(
                    model).__name__
        self.assertEqual(
            {}, broken,
            "a section declares a library-backed model the panel "
            "cannot repoint, so a library switch would leave it "
            "showing the old library: %s" % broken)

    def test_every_switchable_model_the_panel_builds_is_declared(self):
        declared = self._declared()
        undeclared = set()
        for attr in dir(self.panel.pane):
            if attr.startswith("__") or attr in declared:
                continue
            try:
                value = getattr(self.panel.pane, attr)
            except Exception:                            # noqa: BLE001
                continue
            if isinstance(value, type):
                continue
            if callable(getattr(value, "switch_model_data", None)):
                undeclared.add(attr)
        self.assertEqual(
            set(), undeclared,
            "these models can be repointed but no section declares "
            "them, so a library switch leaves them showing the "
            "previous library: %s" % sorted(undeclared))


if __name__ == "__main__":
    unittest.main()
