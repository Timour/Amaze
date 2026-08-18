"""One address form for the row verbs, and a bounds check on every one: `toggle_fav`, `render_thumbnail` and `render_thumbnails` across the AssetLibrary tree each take a ROW, each refuse a row outside the model, and no caller builds a QModelIndex only to take `.row()` off it again. Watch when calling: the models are built with `__new__` and a fixture Prefs, so nothing reaches the machine's real library."""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402,F401

from amaze.core import library, locations  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


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
             mock.patch.object(locations, "set_favourite",
                               lambda prefs, mat_id, on:
                               written.append(mat_id)), \
             mock.patch.object(model, "row_changed", lambda *a, **k: None), \
             mock.patch.object(model, "index", lambda r, c: _FakeIndex(r)), \
             mock.patch.object(model, "rowCount", lambda: len(model._assets)):
            model.toggle_fav(row)
        return written

    def test_a_row_below_the_model_writes_no_star(self):
        """-1 is what an invalid index answers, and a negative index silently resolves to the LAST asset."""
        model = _model(self, 3)
        self.assertEqual(
            [], self._flip(model, -1),
            "a star was written for a row that is not in the model")

    def test_a_row_past_the_end_writes_no_star(self):
        model = _model(self, 3)
        self.assertEqual(
            [], self._flip(model, 7),
            "a star was written for a row past the end of the model")

    def test_the_row_asked_for_is_the_row_starred(self):
        model = _model(self, 3)
        self.assertEqual(["id1"], self._flip(model, 1))


class EveryModelSpellsTheVerbTheSameWay(unittest.TestCase):
    """The same-shape half: one address form across the family, so a reader meets one convention."""

    def _first_arg(self, func):
        import inspect
        names = list(inspect.signature(func).parameters)
        return names[1] if names and names[0] == "self" else names[0]

    def test_every_favourite_verb_takes_a_row(self):
        from amaze.core import file_library
        offenders = []
        for owner, name in ((library.AssetLibrary, "toggle_fav"),
                            (file_library.FileFiles, "toggle_favorite")):
            func = getattr(owner, name, None)
            if func is None:
                continue
            arg = self._first_arg(func)
            if arg != "row":
                offenders.append("%s.%s takes %r" % (
                    owner.__name__, name, arg))
        self.assertEqual([], offenders,
                         "the favourite verb is spelled two ways: %s"
                         % "; ".join(offenders))

    def test_every_thumbnail_verb_takes_a_row(self):
        from amaze.core import code_library, cop_library, gradient_library
        offenders = []
        for owner in (library.AssetLibrary, library.MaterialLibrary,
                      cop_library.CopLibrary, code_library.CodeLibrary,
                      gradient_library.GradientLibrary):
            func = owner.__dict__.get("render_thumbnail")
            if func is None:
                continue
            arg = self._first_arg(func)
            if arg != "row":
                offenders.append("%s.render_thumbnail takes %r"
                                 % (owner.__name__, arg))
        self.assertEqual([], offenders,
                         "the thumbnail verb is spelled two ways: %s"
                         % "; ".join(offenders))

    def test_no_survivor_builds_an_index_to_take_its_row_back(self):
        """`self.index(row, 0)` handed straight to something that calls `.row()` on it is the round-trip this batch removed."""
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        pattern = re.compile(
            r"_add_thumb_paths\(\s*(?:self|model)\.index\(|"
            r"toggle_fav\(\s*(?:self|model)\.index\(")
        for folder, _dirs, files in os.walk(root):
            if os.path.basename(folder) == "tests":
                continue
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, "r", encoding="utf-8") as handle:
                    for number, line in enumerate(handle, 1):
                        if pattern.search(line):
                            offenders.append("%s:%d" % (
                                os.path.relpath(path, root), number))
        self.assertEqual([], offenders,
                         "an index is built only to be taken apart: %s"
                         % ", ".join(offenders))


class ABatchRefusesARowItCannotRender(unittest.TestCase):

    def test_a_row_past_the_end_is_not_rendered(self):
        """`isValid()` cannot answer this: a plain QModelIndex is not invalidated when the rows behind it go away."""
        model = library.MaterialLibrary.__new__(library.MaterialLibrary)
        model.preferences = test_support.fixture_prefs(self)
        model._assets = [_Asset("id0")]
        from amaze.render import thumbs
        from amaze import preview
        rendered = []
        with mock.patch.object(model, "_add_thumb_paths",
                               lambda row: None), \
             mock.patch.object(model, "rowCount", lambda: 1), \
             mock.patch.object(preview, "build_karma_scaffold",
                               lambda preferences: {"net": mock.Mock()}), \
             mock.patch.object(thumbs.ThumbNailRenderer, "create_thumbnail",
                               lambda self, scaffold=None:
                               rendered.append(scaffold)):
            model.render_thumbnails([0, 5])
        self.assertEqual(
            1, len(rendered),
            "a row past the end of the model reached the renderer")


if __name__ == "__main__":
    unittest.main()
