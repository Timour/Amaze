"""A material's textures: each file it uses is copied into its own folder, as `$AMAZEASSET/...`."""

import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze.tests import test_support  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402


def _scratch_library(testcase) -> str:
    folder = tempfile.mkdtemp(prefix="amaze_texlib_")
    testcase.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    return folder


def _prefs_over(folder, path_style="absolute"):
    class Prefs:
        dir = os.path.join(folder, "")
    prefs = Prefs()
    prefs.path_style = path_style
    return prefs


def _pin(testcase, name, value):
    """Set `$name` to `value` for the test; its previous value is restored afterwards."""
    previous = hou.getenv(name)
    if previous is None:
        testcase.addCleanup(hou.unsetenv, name)
    else:
        testcase.addCleanup(hou.putenv, name, previous)
    hou.putenv(name, value)


def _network_with_image(testcase, file_value):
    net = hou.node("/obj").createNode("matnet")
    testcase.addCleanup(net.destroy)
    builder = net.createNode("subnet", "asset")
    image = builder.createNode("mtlximage")
    image.parm("file").set(file_value)
    return builder, image


class TokenPathsTest(unittest.TestCase):
    """The path-only part: $AMAZELIB paths round-trip against a library directory."""

    def test_library_paths_round_trip_and_outside_paths_pass_through(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        absolute = os.path.join(lib, "matX", "Brick", "t.png")
        token = texstore.tokenize(absolute, prefs)
        self.assertEqual("$AMAZELIB/matX/Brick/t.png", token)
        self.assertEqual(os.path.normpath(absolute),
                         os.path.normpath(texstore.resolve(token, prefs)))
        for outside in ("/somewhere/else/t.png", "$ART_MAPS/x/t.png", ""):
            self.assertEqual(outside, texstore.tokenize(outside, prefs))
            self.assertEqual(outside, texstore.resolve(outside, prefs))


class ReferenceScanTest(unittest.TestCase):
    """references() walks FileReference parms, the type Redshift tex0 and mtlximage file declare."""

    def test_only_a_set_file_parm_is_a_reference_and_it_is_found_raw(self):
        from amaze.core import texstore
        builder, image = _network_with_image(self, "$DOES_NOT_MATTER/t.png")
        refs = texstore.references(builder)
        self.assertEqual(["$DOES_NOT_MATTER/t.png"],
                         [raw for _parm, raw in refs])
        self.assertEqual(image.parm("file"), refs[0][0])
        image.parm("file").set("")
        self.assertEqual([], texstore.references(builder))


class CopyIntoLibraryTest(unittest.TestCase):
    """copy_into_library() leaves a reference to a missing file as it was."""

    def test_a_missing_file_is_reported_and_left_alone(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        builder, image = _network_with_image(self, "/gone/never/t.png")
        inventory = texstore.copy_into_library(builder, prefs, "Brick")
        self.assertEqual([], inventory)
        self.assertEqual("/gone/never/t.png",
                         image.parm("file").unexpandedString(),
                         "a dangling reference must stay visible, not "
                         "be rewritten into the library where no file "
                         "was copied")


class RawPathTest(unittest.TestCase):
    """raw_path() is the unexpanded text, or the evaluated path where the parm has keyframes."""

    def test_a_plain_parm_reads_raw_and_a_keyframed_one_reads_evaluated(self):
        from amaze.core import texstore
        builder, image = _network_with_image(self, "$AMAZE_NOT_SET_HERE/t.png")
        self.assertEqual("$AMAZE_NOT_SET_HERE/t.png", texstore.raw_path(image.parm("file")))
        control = builder.createNode("mtlximage", "control")
        control.parm("file").set("/maps/ref.png")
        image.parm("file").setExpression('chs("../control/file")', hou.exprLanguage.Hscript)
        self.assertEqual("/maps/ref.png", texstore.raw_path(image.parm("file")))
        image.parm("file").setExpression('"/maps/" + "py.png"', hou.exprLanguage.Python)
        self.assertEqual("/maps/py.png", texstore.raw_path(image.parm("file")))


class ResolveParmsTest(unittest.TestCase):
    """resolve_parms() on import to the scene: $AMAZELIB paths written as Write Paths As sets."""

    def test_write_paths_as_sets_the_form_of_a_placed_texture(self):
        """Under the chosen variable when the library is inside it, as the File section writes."""
        from amaze.core import texstore
        from amaze.helpers import helpers
        lib = _scratch_library(self)
        folder = os.path.dirname(os.path.normpath(lib))
        tail = "/".join((os.path.basename(os.path.normpath(lib)), "matX", "Brick", "t.png"))
        for style, name in (("hip", "HIP"), ("job", "JOB")):
            with self.subTest(style=style):
                _pin(self, name, folder)
                builder, image = _network_with_image(self, "$AMAZELIB/matX/Brick/t.png")
                self.assertEqual(1, texstore.resolve_parms(
                    builder, _prefs_over(lib, style), helpers.houdini_path))
                self.assertEqual("$%s/%s" % (name, tail), image.parm("file").unexpandedString())

    def test_token_parms_become_absolute_and_others_are_untouched(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        builder, image = _network_with_image(
            self, "$AMAZELIB/matX/Brick/t.png")
        changed = texstore.resolve_parms(builder, prefs)
        self.assertEqual(1, changed)
        self.assertEqual(
            os.path.normpath(os.path.join(lib, "matX", "Brick", "t.png")),
            os.path.normpath(image.parm("file").unexpandedString()))
        image.parm("file").set("$ART_MAPS/t.png")
        self.assertEqual(0, texstore.resolve_parms(builder, prefs))
        self.assertEqual("$ART_MAPS/t.png",
                         image.parm("file").unexpandedString())


class SaveFromNodeTest(unittest.TestCase):
    """Saving copies textures from the staged copy, not the scene node; the row holds the inventory."""

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")    # save_node requires $OCIO
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _outside_texture(self, name="fabric_diff.png"):
        outside = tempfile.mkdtemp(prefix="amaze_outside_")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        path = os.path.join(outside, name)
        with open(path, "wb") as handle:
            handle.write(b"pngbytes")
        return path

    def _saveable_builder(self, name, texture_path):
        from amaze.tests import make_library_fixture
        builder = make_library_fixture.build_material(
            hou.node("/mat"), name, (0.5, 0.5, 0.5))
        self.addCleanup(builder.destroy)
        image = builder.createNode("mtlximage")
        image.parm("file").set(texture_path)
        return builder, image

    def test_copy_to_scene_writes_textures_in_the_write_paths_as_form(self):
        """A placed material's library textures resolve, written under `$JOB` when that is chosen."""
        from amaze.core import texstore
        from amaze.render import nodes as nodes_mod
        model = self.panel.pane.material_model
        prefs = model.preferences
        source = self._outside_texture("resolved_diff.png")
        builder, _image = self._saveable_builder("Resolved_Fabric", source)
        held = test_support.asset_ids(model)
        self.assertTrue(material_actions.add_asset(model, builder, "Fabrics", "", False))
        row, = test_support.arrived(model, held)
        _pin(self, "JOB", os.path.dirname(os.path.normpath(prefs.dir)))
        self.addCleanup(setattr, prefs, "path_style", prefs.path_style)
        prefs.path_style = "job"
        handler = nodes_mod.NodeHandler(prefs)
        ok, reason, created = handler.import_asset_to_scene(row, "/mat")
        self.assertTrue(ok, reason)
        self.addCleanup(created[0].destroy)
        refs = [raw for _p, raw in texstore.references(created[0])]
        self.assertTrue(refs, "premise: the imported network has a "
                              "file reference")
        for raw in refs:
            self.assertTrue(raw.startswith("$JOB/"),
                            "Write Paths As was not followed: %s" % raw)
            self.assertTrue(os.path.isfile(hou.text.expandString(raw)),
                            "the scene reference does not resolve: %s"
                            % raw)


class PanelEnvTest(unittest.TestCase):
    """The panel publishes $AMAZELIB at startup, so Houdini resolves store references unaided."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_fixture_panel_published_the_variable(self):
        self.assertEqual(
            os.path.normpath(self.panel.pane.prefs.dir),
            os.path.normpath(hou.getenv("AMAZELIB") or ""),
            "panel startup did not publish $AMAZELIB")


class EverySwitchPublishesTheVariable(unittest.TestCase):
    """Reload Library and Preferences' Apply point $AMAZELIB at the library they open."""

    def setUp(self):
        previous = hou.getenv("AMAZELIB")
        if previous is None:
            self.addCleanup(hou.unsetenv, "AMAZELIB")
        else:
            self.addCleanup(hou.putenv, "AMAZELIB", previous)
        self.panel = test_support.fixture_panel(self)

    def _assert_published(self, library):
        self.assertEqual(
            os.path.normpath(library),
            os.path.normpath(hou.getenv("AMAZELIB") or ""),
            "$AMAZELIB still names the previous library until Preferences "
            "closes, so a render reads that library's textures")

    def _write_settings(self, **changes):
        settings = os.path.join(self.panel.pane.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(changes)
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_reload_library(self):
        other = test_support.seeded_library(self)
        self._write_settings(directory=other)
        self.panel.pane.library.reload()
        self._assert_published(other)

    def test_preferences_apply(self):
        other = test_support.seeded_library(self)
        self.assertTrue(test_support.apply_library(self, self.panel, other))
        self._assert_published(other)


if __name__ == "__main__":
    unittest.main()
