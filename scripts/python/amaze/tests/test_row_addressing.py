"""A star and a render each take a ROW and refuse one outside the model; fixture Prefs only."""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402,F401

from amaze.core import library, locations  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the log


class _Asset:

    def __init__(self, mat_id):
        self.mat_id = mat_id


class _FakeIndex:
    """Stands in for `self.index(row, 0)` on a model built with __new__."""

    def __init__(self, row):
        self._row = row

    def row(self):
        return self._row


def _model(testcase, count):
    model = library.AssetLibrary.__new__(library.AssetLibrary)
    model.preferences = test_support.fixture_prefs(testcase)
    model._assets = [_Asset("id%d" % i) for i in range(count)]
    return model


class AStarNeverLandsOnARowThatWasNotAskedFor(unittest.TestCase):

    def _flip(self, model, row):
        """Record which mat_id the star was written against."""
        written = []
        with mock.patch.object(locations, "is_favourite",
                               lambda prefs, mat_id: False), \
             mock.patch.object(locations, "set_favourites",
                               lambda prefs, wanted:
                               written.extend(wanted)), \
             mock.patch.object(model, "row_changed", lambda *a, **k: None), \
             mock.patch.object(model, "index", lambda r, c: _FakeIndex(r)), \
             mock.patch.object(model, "rowCount", lambda: len(model._assets)):
            model.toggle_fav(row)
        return written

    def test_the_row_asked_for_is_the_row_starred(self):
        for row, starred in ((-1, []), (7, []), (1, ["id1"])):
            with self.subTest(row=row):
                self.assertEqual(
                    starred, self._flip(_model(self, 3), row),
                    "row %d starred the wrong asset - an invalid index "
                    "answers -1, which resolves to the LAST one" % row)


class ABatchRefusesARowItCannotRender(unittest.TestCase):

    def test_a_row_past_the_end_is_not_rendered(self):
        """`isValid()` cannot answer this: a plain QModelIndex is not invalidated when the rows behind it go away."""
        model = library.MaterialLibrary.__new__(library.MaterialLibrary)
        model.preferences = test_support.fixture_prefs(self)
        model._assets = [_Asset("id0")]
        from amaze.render import thumbs
        rendered = []
        with mock.patch.object(model, "_add_thumb_paths",
                               lambda row: None), \
             mock.patch.object(model, "rowCount", lambda: 1), \
             mock.patch.object(thumbs.ThumbNailRenderer, "render_assets",
                               lambda preferences, mats: rendered.extend(mats)):
            material_actions.render_thumbnails(model, [0, 5])
        self.assertEqual(
            1, len(rendered),
            "a row past the end of the model reached the renderer")


if __name__ == "__main__":
    unittest.main()
