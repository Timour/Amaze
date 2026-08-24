"""The texture store: every file a material references is adopted INTO the library and referenced as `$AMAZELIB/...`, so the library is self-contained and survives moves, renames and other machines - the export door packs what the inventory names, and Copy To hands scenes plain absolute paths."""

import os
import shutil
import tempfile
import unittest

from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze.tests import test_support  # noqa: E402


def _scratch_library(testcase) -> str:
    folder = tempfile.mkdtemp(prefix="amaze_texlib_")
    testcase.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    return folder


def _prefs_over(folder):
    class Prefs:
        dir = os.path.join(folder, "")
    return Prefs()


def _network_with_image(testcase, file_value):
    net = hou.node("/obj").createNode("matnet")
    testcase.addCleanup(net.destroy)
    builder = net.createNode("subnet", "asset")
    image = builder.createNode("mtlximage")
    image.parm("file").set(file_value)
    return builder, image


class TokenPathsTest(unittest.TestCase):
    """The pure path half: $AMAZELIB spellings round-trip against a library directory."""

    def test_tokenize_and_resolve_round_trip(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        absolute = os.path.join(lib, "matX", "Brick", "t.png")
        token = texstore.tokenize(absolute, prefs)
        self.assertEqual("$AMAZELIB/matX/Brick/t.png", token)
        self.assertEqual(os.path.normpath(absolute),
                         os.path.normpath(texstore.resolve(token, prefs)))

    def test_paths_outside_the_library_pass_through_unchanged(self):
        from amaze.core import texstore
        prefs = _prefs_over(_scratch_library(self))
        for outside in ("/somewhere/else/t.png", "$ART_MAPS/x/t.png", ""):
            self.assertEqual(outside, texstore.tokenize(outside, prefs))
            self.assertEqual(outside, texstore.resolve(outside, prefs))


class ReferenceScanTest(unittest.TestCase):
    """references() walks a network's FileReference parms - the probe showed Redshift tex0 and mtlximage file both declare the type."""

    def test_an_image_file_parm_is_found_raw(self):
        from amaze.core import texstore
        builder, image = _network_with_image(self, "$DOES_NOT_MATTER/t.png")
        refs = texstore.references(builder)
        self.assertEqual(["$DOES_NOT_MATTER/t.png"],
                         [raw for _parm, raw in refs])
        self.assertEqual(image.parm("file"), refs[0][0])

    def test_empty_and_non_file_parms_are_not_references(self):
        from amaze.core import texstore
        builder, image = _network_with_image(self, "")
        self.assertEqual([], texstore.references(builder))


class AdoptTest(unittest.TestCase):
    """adopt() copies referenced files INTO the library and rewrites the parms to $AMAZELIB - the inventory it returns is what the export packs."""

    def _outside_texture(self):
        outside = tempfile.mkdtemp(prefix="amaze_outside_")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        path = os.path.join(outside, "brick_diff.png")
        with open(path, "wb") as handle:
            handle.write(b"pngbytes")
        return path

    def test_an_outside_file_is_copied_in_and_the_parm_rewritten(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        source = self._outside_texture()
        builder, image = _network_with_image(self, source)
        inventory = texstore.adopt(builder, prefs, "Brick__test-1")
        expected = "$AMAZELIB/matX/Brick__test-1/textures/brick_diff.png"
        self.assertEqual([expected], inventory)
        self.assertEqual(expected, image.parm("file").unexpandedString())
        landed = os.path.join(lib, "matX", "Brick__test-1", "textures",
                              "brick_diff.png")
        self.assertTrue(os.path.isfile(landed), "the file was not adopted")
        with open(landed, "rb") as handle:
            self.assertEqual(b"pngbytes", handle.read())

    def test_a_file_already_under_the_library_is_tokenized_not_copied(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        inside = os.path.join(lib, "matX", "Old_Pack", "t.png")
        os.makedirs(os.path.dirname(inside))
        with open(inside, "wb") as handle:
            handle.write(b"x")
        builder, image = _network_with_image(self, inside)
        inventory = texstore.adopt(builder, prefs, "ignored")
        self.assertEqual(["$AMAZELIB/matX/Old_Pack/t.png"], inventory)
        self.assertFalse(
            os.path.exists(os.path.join(lib, "matX", "ignored")),
            "a file already inside the library was copied a second time")

    def test_a_missing_file_is_reported_and_left_alone(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        builder, image = _network_with_image(self, "/gone/never/t.png")
        inventory = texstore.adopt(builder, prefs, "Brick")
        self.assertEqual([], inventory)
        self.assertEqual("/gone/never/t.png",
                         image.parm("file").unexpandedString(),
                         "a dangling reference must stay visible, not "
                         "be rewritten into the library where nothing "
                         "landed")

    def test_a_locked_parm_stays_visible_and_out_of_the_inventory(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        source = self._outside_texture()
        builder, image = _network_with_image(self, source)
        image.parm("file").lock(True)
        inventory = texstore.adopt(builder, prefs, "Brick__locked")
        self.assertEqual([], inventory,
                         "a token the network does not actually carry "
                         "was promised to the row - export would pack "
                         "a texture nothing references")
        self.assertEqual(source, image.parm("file").unexpandedString(),
                         "the locked parm was rewritten")

    def test_adopt_file_answers_a_token_and_lands_the_bytes(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        source = self._outside_texture()
        token = texstore.adopt_file(source, prefs, "Brick__file")
        self.assertEqual(
            "$AMAZELIB/matX/Brick__file/textures/brick_diff.png", token)
        self.assertTrue(os.path.isfile(texstore.resolve(token, prefs)))
        self.assertEqual("", texstore.adopt_file("/gone/t.png", prefs,
                                                 "Brick__file"))

    def test_an_env_reference_is_expanded_before_adoption(self):
        from amaze.core import texstore
        lib = _scratch_library(self)
        prefs = _prefs_over(lib)
        source = self._outside_texture()
        hou.putenv("AMAZE_TEST_MAPS", os.path.dirname(source))
        self.addCleanup(hou.unsetenv, "AMAZE_TEST_MAPS")
        builder, image = _network_with_image(
            self, "$AMAZE_TEST_MAPS/brick_diff.png")
        inventory = texstore.adopt(builder, prefs, "Brick__env")
        self.assertEqual(
            ["$AMAZELIB/matX/Brick__env/textures/brick_diff.png"],
            inventory)
        self.assertTrue(os.path.isfile(os.path.join(
            lib, "matX", "Brick__env", "textures", "brick_diff.png")))


class ResolveParmsTest(unittest.TestCase):
    """resolve_parms() is the scene-side door: $AMAZELIB leaves the building as a plain absolute path, so scenes carry no Amaze dependency."""

    def test_token_parms_become_absolute(self):
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

    def test_non_token_parms_are_untouched(self):
        from amaze.core import texstore
        prefs = _prefs_over(_scratch_library(self))
        builder, image = _network_with_image(self, "$ART_MAPS/t.png")
        self.assertEqual(0, texstore.resolve_parms(builder, prefs))
        self.assertEqual("$ART_MAPS/t.png",
                         image.parm("file").unexpandedString())


class PutenvTest(unittest.TestCase):
    """The panel publishes $AMAZELIB at startup so Houdini itself resolves library references in thumbnails and previews - no door to miss."""

    def test_publish_sets_the_variable_to_the_library(self):
        from amaze.core import texstore
        prior = hou.getenv(texstore.TOKEN_VAR)
        self.addCleanup(hou.putenv, texstore.TOKEN_VAR, prior or "")    # later modules in this hython inherit the variable - never leave it aimed at a deleted scratch
        lib = _scratch_library(self)
        texstore.publish_env(_prefs_over(lib))
        self.assertEqual(os.path.normpath(lib),
                         os.path.normpath(hou.getenv("AMAZELIB") or ""))


class SaveDoorTest(unittest.TestCase):
    """Save to Amaze adopts: the STAGED copy is rewritten and its files copied in - the user's scene node is never touched, and the row carries the token inventory."""

    @classmethod
    def setUpClass(cls):
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

    def test_saving_adopts_and_the_scene_node_stays_untouched(self):
        from amaze.core import material
        model = self.panel.material_model
        prefs = model.preferences
        source = self._outside_texture()
        builder, image = self._saveable_builder("Adopted_Fabric", source)
        before = model.rowCount()
        renderer = model.add_asset(builder, "Fabrics", "", False)
        self.assertTrue(renderer, "premise: the save went through")
        self.assertEqual(before + 1, model.rowCount())
        self.assertEqual(source, image.parm("file").unexpandedString(),
                         "the SCENE node was rewritten - adoption must "
                         "happen on the staged copy only")
        row = model.assets[-1]
        tokens = (row.get_as_dict().get("textures") or [])
        self.assertEqual(1, len(tokens), "the row carries no inventory")
        self.assertTrue(tokens[0].startswith("$AMAZELIB/matX/"), tokens)
        from amaze.core import texstore
        landed = texstore.resolve(tokens[0], prefs)
        self.assertTrue(os.path.isfile(landed),
                        "the referenced file was not adopted")
        mat_file = material.payload_path(prefs, str(row.mat_id),
                                         prefs.ext)
        with open(mat_file, "rb") as handle:
            payload = handle.read()
        self.assertIn(b"$AMAZELIB/matX/", payload,
                      "the saved network still references the outside "
                      "path")
        self.assertNotIn(source.encode(), payload)

    def test_copy_to_scene_resolves_tokens_to_absolute_paths(self):
        from amaze.core import texstore
        from amaze.render import nodes as nodes_mod
        model = self.panel.material_model
        prefs = model.preferences
        source = self._outside_texture("resolved_diff.png")
        builder, _image = self._saveable_builder("Resolved_Fabric", source)
        self.assertTrue(model.add_asset(builder, "Fabrics", "", False))
        row = model.assets[-1]
        handler = nodes_mod.NodeHandler(prefs)
        ok, reason, created = handler.import_asset_to_scene(row, "/mat")
        self.assertTrue(ok, reason)
        self.addCleanup(created[0].destroy)
        refs = [raw for _p, raw in texstore.references(created[0])]
        self.assertTrue(refs, "premise: the landed network has a "
                              "file reference")
        for raw in refs:
            self.assertFalse(raw.startswith("$AMAZELIB"),
                             "a token leaked into the scene: %s" % raw)
            self.assertTrue(os.path.isfile(hou.text.expandString(raw)),
                            "the scene reference does not resolve: %s"
                            % raw)


class PanelEnvTest(unittest.TestCase):
    """The panel publishes $AMAZELIB at startup, so Houdini resolves store references without any door's help."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_fixture_panel_published_the_variable(self):
        self.assertEqual(
            os.path.normpath(self.panel.prefs.dir),
            os.path.normpath(hou.getenv("AMAZELIB") or ""),
            "panel startup did not publish $AMAZELIB")


if __name__ == "__main__":
    unittest.main()
