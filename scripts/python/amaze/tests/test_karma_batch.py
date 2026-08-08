"""One Karma scaffold per BATCH, not per material.

The scaffold is a full USD stage composition - the expensive half of
a Karma thumbnail, and byte-identical for every material.
`build_karma_scaffold` and `render_karma_into` were written to be
shared across a batch and had no caller doing it: every render built
its own and destroyed it, so re-rendering N materials paid the stage
load N times.

Counted, not timed. A wall-clock assertion on a real Karma render is
a flaky test about the machine; the claim here is exactly "one build
for N renders", which is a count.
"""

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

from amaze.render import thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class _Index:
    """Only what render_thumbnails reads off an index."""

    def __init__(self, row):
        self._row = row

    def isValid(self):
        return True

    def row(self):
        return self._row


class TheScaffoldIsBuiltOncePerBatch(unittest.TestCase):

    def _model(self, count):
        from amaze.core import library
        model = library.MaterialLibrary.__new__(library.MaterialLibrary)
        model.preferences = test_support.fixture_prefs(self)
        model._assets = [mock.Mock(name="asset%d" % i) for i in range(count)]
        model._add_thumb_paths = lambda index: None
        return model

    def test_ten_materials_build_one_scaffold(self):
        model = self._model(10)
        built = []
        rendered = []

        def fake_build(self):
            built.append(1)
            return {"net": mock.Mock()}

        with mock.patch.object(thumbs.ThumbNailRenderer,
                               "build_karma_scaffold", fake_build), \
             mock.patch.object(thumbs.ThumbNailRenderer, "create_thumbnail",
                               lambda self, scaffold=None:
                               rendered.append(scaffold)):
            model.render_thumbnails([_Index(i) for i in range(10)])

        self.assertEqual(1, len(built),
                         "the USD stage was composed %d times for one "
                         "batch of ten" % len(built))
        self.assertEqual(10, len(rendered), "not every material rendered")
        self.assertTrue(
            all(s is rendered[0] for s in rendered),
            "the materials did not all render into the SAME scaffold")

    def test_a_single_render_is_a_batch_of_one(self):
        """render_thumbnail keeps working and takes the same path -
        no second way to render one material."""
        model = self._model(1)
        built = []
        with mock.patch.object(thumbs.ThumbNailRenderer,
                               "build_karma_scaffold",
                               lambda self: built.append(1) or {"net": mock.Mock()}), \
             mock.patch.object(thumbs.ThumbNailRenderer, "create_thumbnail",
                               lambda self, scaffold=None: None):
            model.render_thumbnail(_Index(0))
        self.assertEqual(1, len(built))

    def test_the_batch_destroys_its_scaffold_once(self):
        """Both ends, and off the undo stack - a bare destroy is the
        half that resurrects the whole scaffold on one Ctrl+Z."""
        net = mock.Mock()
        with mock.patch.object(thumbs.ThumbNailRenderer,
                               "build_karma_scaffold",
                               lambda self: {"net": net}):
            with thumbs.ThumbNailRenderer.karma_batch(
                    test_support.fixture_prefs(self)) as scaffold:
                self.assertIsNotNone(scaffold)
                net.destroy.assert_not_called()
        net.destroy.assert_called_once()

    def test_no_scene_viewer_falls_back_instead_of_failing(self):
        """build_karma_scaffold answers None with no Scene Viewer to
        take OCIO display/view from; the batch must still render, each
        material building its own as before."""
        with mock.patch.object(thumbs.ThumbNailRenderer,
                               "build_karma_scaffold", lambda self: None):
            with thumbs.ThumbNailRenderer.karma_batch(
                    test_support.fixture_prefs(self)) as scaffold:
                self.assertIsNone(scaffold)


if __name__ == "__main__":
    unittest.main()
