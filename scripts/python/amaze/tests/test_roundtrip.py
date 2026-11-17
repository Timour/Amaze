"""Save/load round-trip on real fixture files: values read back equal; a failed save adds no row."""

import os
import stat
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(  # three dirnames reach python/; four would test the install ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import json  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.core import library as library_mod  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.core import material_files  # noqa: E402
from amaze.core import asset_record, library_files, material, renderers  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS = library_files.MATERIALS

SPEC = {  # distinctive non-default values: these numbers must read back unchanged after a save
    "base_color": (0.123, 0.456, 0.789),
    "specular_roughness": 0.321,
    "metalness": 1.0,
    "specular_IOR": 1.77,
}


def _build_material(parent: hou.Node, name: str) -> hou.Node:
    """A real Karma material built by `nodes.build_karma_material`."""

    def produce(builder):
        shader = builder.createNode("mtlxstandard_surface")
        for parm, value in SPEC.items():
            if isinstance(value, tuple):
                shader.parmTuple(parm).set(value)
            else:
                shader.parm(parm).set(value)
        return shader

    return nodes.build_karma_material(parent, name, produce).builder  # by name: the engine returns a nodes.KarmaMaterial, not a bare pair


def _shader_of(builder: hou.Node):
    return next(n for n in builder.children()
                if n.type().name() == "mtlxstandard_surface")


class TestRoundTrip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")    # save_node checks $OCIO; nothing renders here

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)
        mat = hou.node("/mat")
        self._mat_before = set(mat.children()) if mat else set()

    def tearDown(self):
        mat = hou.node("/mat")
        if mat:
            for child in set(mat.children()) - self._mat_before:
                try:
                    child.destroy()
                except hou.Error:
                    pass

    # -- the .mat and the .json are one unit -----------------------------

    def test_a_mat_write_that_fails_or_writes_nothing_keeps_the_old_pair(self):
        """The builder and the .mat ARE one asset: neither may change alone. ▸p/asset-write-unit"""
        base = material.section_folder(self.prefs.dir, MATERIALS)
        os.makedirs(base, exist_ok=True)
        record = asset_record.path_for(self.prefs, "pairtest", MATERIALS)
        mat = os.path.join(base, "pairtest" + self.prefs.ext)
        old = {"type": "subnet", "interface": "OLD INTERFACE", "values": {}}
        handler = nodes.NodeHandler(self.prefs)
        builder = self.staging.createNode("subnet", "pair_builder")

        def raise_disk_full(path):
            raise hou.OperationFailed("disk full")

        for why, writer in (("the write raises", raise_disk_full),
                            ("the writer returns with no file", lambda path: None)):
            with self.subTest(why):
                asset_record.write_section(record, asset_record.BUILDER, old)
                with open(mat, "w", encoding="utf-8") as handle:
                    handle.write("OLD MAT")
                with self.assertRaises(hou.Error):
                    handler.save_asset_pair(mat, writer, builder, "pairtest")
                self.assertEqual(
                    old, asset_record.read(record)["builder"],
                    "a failed .mat write replaced the previous builder")
                with open(mat, encoding="utf-8") as handle:
                    self.assertEqual("OLD MAT", handle.read())
                self.assertEqual([], [n for n in os.listdir(base) if n.endswith(".writing")],
                                 "temp files were left after a failed save")

    def test_a_good_save_updates_both(self):
        base = material.section_folder(self.prefs.dir, MATERIALS)
        mat = os.path.join(base, "good" + self.prefs.ext)
        handler = nodes.NodeHandler(self.prefs)
        builder = self.staging.createNode("subnet", "good_builder")
        handler.save_asset_pair(
            mat, lambda path: open(path, "w", encoding="utf-8").write("NEW MAT"),
            builder, "good")
        saved = asset_record.read(asset_record.path_for(self.prefs, "good", MATERIALS))
        self.assertEqual("subnet", saved["builder"].get("type"))
        self.assertEqual(builder.parmTemplateGroup().asDialogScript(),
                         saved["builder"].get("interface"))
        self.assertEqual({}, saved["metadata"], "a save of the pair wrote metadata it was not given")
        self.assertFalse(os.path.exists(os.path.join(base, "good.interface")),
                         "a format 4 save still wrote the retired .interface")
        with open(mat, encoding="utf-8") as handle:
            self.assertEqual("NEW MAT", handle.read())

    def test_saving_a_bare_shader_does_not_archive_the_connector(self):  # -- what a save must NOT archive --
        """A bare shader's save must not archive the builder's connector, or the import renders black."""
        builder = _build_material(self.staging, "bare_probe")
        shader = _shader_of(builder)
        texture = builder.createNode("mtlximage")
        shader.setInput(1, texture)

        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, shader, "Bare", "", False)
        asset, = test_support.arrived(self.model, held)

        handler = nodes.NodeHandler(self.prefs)
        ok, reason, _created = handler.import_asset_to_scene(asset, target="mat")
        self.assertTrue(ok, reason)

        imported = handler.builder_node
        connectors = [c for c in imported.children()
                      if c.type().name() == "subnetconnector"
                      and "surface" in c.name()]
        self.assertEqual(
            1, len(connectors),
            "the saved material carried a duplicate surface connector: %s"
            % [c.name() for c in connectors])
        self.assertTrue(
            nodes.surface_terminal_wired(imported),
            "the imported material has nothing wired to its surface "
            "terminal - it renders black")

    def test_a_save_of_a_builders_contents_imports_with_one_set_of_terminals(self):
        """A save holding the builder's own connectors imports with them alone, wired. ▸r/save-shape"""
        asset = next(a for a in self.model.assets if a.name == "plastic")    # such a save
        handler = nodes.NodeHandler(self.prefs)
        ok, reason, _created = handler.import_asset_to_scene(asset, target="mat")
        self.assertTrue(ok, reason)
        imported = handler.builder_node
        outputs = sorted((c.name(), c.parm("parmname").eval()) for c in imported.children()
                         if c.type().name() == "subnetconnector"
                         and c.parm("connectorkind").eval() == 1)
        self.assertEqual([("displacement_output", "displacement"),
                          ("surface_output", "surface")], outputs,
                         "the import holds a second set of output connectors")
        self.assertTrue(nodes.surface_terminal_wired(imported),
                        "the imported material renders the default grey")
        self.assertEqual(1, len([c for c in imported.children()
                                 if c.type().name() == "subinput"]))

    @unittest.skipUnless(test_support.renderer_loaded("Redshift"),
                         "the Redshift plugin is not loaded")
    def test_an_import_keeps_its_builder(self):
        """A rebuilt builder node is kept and moved, not emptied into loose VOPs in /mat."""
        mat_ctx = hou.node("/mat") or hou.node("/").createNode("mat")
        source = mat_ctx.createNode("redshift_vopnet", "rs_src")
        source.setGenericFlag(hou.nodeFlag.Material, True)

        before = {n.path() for n in mat_ctx.children()}
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, source, "RedshiftProbe", "", False)
        asset, = test_support.arrived(self.model, held)
        self.assertEqual(
            "Redshift", asset.renderer,
            "this test needs a Redshift asset to test anything")

        ok, reason, _created = nodes.NodeHandler(
            self.prefs).import_asset_to_scene(asset, target="mat")
        self.assertTrue(ok, reason)

        created = [c for c in mat_ctx.children() if c.path() not in before]  # by PATH: hou.Node wrappers are not identity-stable
        loose = [c for c in created
                 if c.type().name() != "rs_usd_material_builder"]    # a classic one is saved as it
        self.assertEqual(
            [], [c.name() for c in loose],
            "the import left loose VOPs in /mat instead of "
            "rebuilding a material")
        builders = [c for c in created
                    if c.type().name() == "rs_usd_material_builder"]
        self.assertEqual(1, len(builders), "expected exactly one builder")
        self.assertTrue(
            builders[0].children(),
            "the rebuilt builder is empty - its contents went elsewhere")
        for node in created:
            try:
                node.destroy()
            except Exception:            # noqa: BLE001 - already gone
                pass

    def test_sop_imports_reuse_one_matnet(self):  # -- clutter and containment --
        """SOP imports reuse one matnet, as LOP imports reuse a materiallibrary, never one per import."""
        geo = hou.node("/obj").createNode("geo", "sop_reuse_probe")
        self.addCleanup(geo.destroy)
        for _ in range(3):
            handler = nodes.NodeHandler(self.prefs)
            handler.get_current_network_node = lambda g=geo: g
            handler._set_sop_import_path()
        matnets = [c for c in geo.children()
                   if c.type().name() == "matnet"]
        self.assertEqual(
            1, len(matnets),
            "three imports left %d matnets in one geo" % len(matnets))

    def _failing_lop_import(self, context):
        """Import a Karma asset whose `.mat` is damaged into `context`; returns the import's ok."""
        asset = next(a for a in self.model.assets
                     if renderers.is_karma(a.renderer))
        payload = material.payload_path(self.prefs, asset.mat_id,
                                        self.prefs.ext, MATERIALS)
        with open(payload, "w", encoding="utf-8") as handle:
            handle.write("not an items file")
        ok, _reason, _created = nodes.NodeHandler(
            self.prefs).import_asset_to_scene(
                asset, target="lop", context_node=context)
        return ok

    def _libraries(self, stage):
        return [c.name() for c in stage.children()
                if c.type().name() == "materiallibrary"]

    def test_a_lop_import_is_created_in_the_library_it_is_given_or_nowhere(self):
        """Outside a Material Library an import makes nothing; inside one, a bad load keeps it."""
        from amaze import messages
        stage = hou.node("/obj").createNode("lopnet", "lop_landing_probe")
        self.addCleanup(stage.destroy)
        ok, reason, _created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            self._karma_asset(), target="lop", context_node=stage)
        self.assertFalse(ok, "an import outside a Material Library went ahead")
        self.assertEqual(messages.LOP_IMPORT_OUTSIDE_LIBRARY, reason)
        self.assertEqual([], self._libraries(stage),
                         "the import made a library on its own")
        theirs = stage.createNode("materiallibrary", "theirs")
        self.assertFalse(self._failing_lop_import(theirs),
                         "premise: a damaged .mat must fail the import")
        self.assertEqual(["theirs"], self._libraries(stage),
                         "a failed import removed the library it was given")

    def test_karma_destination_is_the_library_or_nothing_in_solaris(self):
        """The online import and Generate write into the current Material Library, or nowhere."""
        stage = hou.node("/obj").createNode("lopnet", "destination_probe")
        self.addCleanup(stage.destroy)
        with mock.patch.object(nodes.NodeHandler, "get_current_network_node",
                               return_value=stage):
            self.assertIsNone(nodes.karma_destination(self.prefs),
                              "a LOP network outside a library was given a destination")
        self.assertEqual([], self._libraries(stage),
                         "karma_destination made a library on its own")
        theirs = stage.createNode("materiallibrary", "theirs")
        with mock.patch.object(nodes.NodeHandler, "get_current_network_node",
                               return_value=theirs):
            self.assertEqual(theirs, nodes.karma_destination(self.prefs))

    def _karma_asset(self):
        return next(a for a in self.model.assets
                    if renderers.is_karma(a.renderer))

    def _assert_import_returns_the_reason(self, handler, stage):
        """The staging failure returns the message naming the material, and never raises."""
        from amaze import messages
        asset = self._karma_asset()
        try:
            ok, reason, created = handler.import_asset_to_scene(
                asset, target="lop", context_node=stage)
        except hou.Error as exc:
            self.fail("the staging failure raised instead of returning a reason: %s"
                      % exc)
        self.assertFalse(ok)
        self.assertEqual(
            messages.MATERIAL_FAILED_TO_IMPORT % asset.name, reason)
        self.assertEqual([], created)

    def test_a_companion_that_raises_keeps_the_library_it_was_given(self):
        stage = hou.node("/obj").createNode("lopnet", "companion_raise_probe")
        self.addCleanup(stage.destroy)
        theirs = stage.createNode("materiallibrary", "theirs")
        handler = nodes.NodeHandler(self.prefs)

        def raise_operation_failed(mat, beside):
            raise hou.OperationFailed("companion refused")

        handler.restore_cop_companion = raise_operation_failed
        self._assert_import_returns_the_reason(handler, theirs)
        self.assertEqual(["theirs"], self._libraries(stage),
                         "the import removed the library it was given when "
                         "the COP companion raised")
        self.assertIsNone(handler._context_override,
                          "the import kept the context it was given")

    def test_a_staging_failure_removes_the_restored_companion(self):
        """The companion is restored before the staging network exists; a failure removes both."""
        stage = hou.node("/obj").createNode("lopnet", "staging_raise_probe")
        self.addCleanup(stage.destroy)
        library = stage.createNode("materiallibrary", "theirs")
        real_node = hou.node
        self.addCleanup(lambda: [n.destroy() for n in
                                 [real_node("/obj/staging_probe_cops")]
                                 if n is not None])
        handler = nodes.NodeHandler(self.prefs)
        handler.restore_cop_companion = lambda mat, beside: real_node(
            "/obj").createNode("copnet", "staging_probe_cops")

        class RaisesOnStaging:
            def __init__(self, node):
                self._node = node

            def createNode(self, type_name, *args, **kwargs):
                if type_name == "matnet":
                    raise hou.OperationFailed("staging refused")
                return self._node.createNode(type_name, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._node, name)

        def node(path):
            found = real_node(path)
            return RaisesOnStaging(found) if path == "/obj" else found

        with mock.patch.object(hou, "node", node):
            self._assert_import_returns_the_reason(handler, library)
        self.assertIsNone(real_node("/obj/staging_probe_cops"),
                          "the import left the COP companion it restored")
        self.assertEqual(["theirs"], self._libraries(stage))

    def test_a_builder_is_saved_whole_with_its_own_data(self):
        """A MaterialX builder saves whole, so data on the builder itself comes back with it."""
        builder = _build_material(self.staging, "whole_probe")
        builder.setUserData("amaze_whole_probe", "1")
        held = test_support.asset_ids(self.model)
        self.assertEqual("Karma", material_actions.add_asset(
            self.model, builder, "", "", False))
        asset, = test_support.arrived(self.model, held)
        ok, reason, created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            asset, target="mat")
        self.assertTrue(ok, reason)
        self.assertEqual("1", created[0].userData("amaze_whole_probe"),
                         "the builder was saved as its contents, so its own data was not saved")

    def test_saved_material_is_written_to_disk_and_reimports(self):  # -- the round-trip --
        rows_before = self.model.rowCount()
        builder = _build_material(self.staging, "roundtrip_mat")
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, builder, "RoundTrip", "roundtrip,test", False)

        self.assertEqual(self.model.rowCount(), rows_before + 1)  # one row added; the node keeps its id for re-saves
        mat_id = str(test_support.arrived(self.model, held)[0].mat_id)
        self.assertEqual(builder.userData("assetlib_id"), mat_id)

        base = os.path.join(material.section_folder(self.prefs.dir, MATERIALS), mat_id)  # both files exist, non-empty
        for path in (base + self.prefs.ext, base + ".json"):
            self.assertTrue(os.path.exists(path), path)
            self.assertGreater(os.path.getsize(path), 0, path)
        self.assertEqual(builder.type().name(),
                         asset_record.read(base + ".json")["builder"].get("type"),
                         "the save's .json does not name the builder it saved")
        for retired in (".interface", ".builder.json"):
            self.assertFalse(os.path.exists(base + retired),
                             "a format 4 save still wrote %s" % retired)

        test_support.reset_database_singletons()  # persistence: a fresh model over the same dir, so the row comes from the database
        reloaded = library_mod.MaterialLibrary(preferences=self.prefs)
        row = reloaded.find_asset_row_by_id(mat_id)
        self.assertNotEqual(row, -1, "saved row missing after reload")
        asset = reloaded.assets[row]
        self.assertEqual(asset.name, "roundtrip_mat")
        self.assertIn("RoundTrip", asset.categories)

        ok, reason, _created = material_actions.import_asset_to_scene(reloaded,   # RE-IMPORT through the real importer, into /mat
            reloaded.index(row, 0), target="mat"
        )
        self.assertTrue(ok, reason)
        imported = [n for n in hou.node("/mat").children()
                    if n not in self._mat_before
                    and n.userData("assetlib_id") == mat_id]
        self.assertEqual(len(imported), 1,
                         "expected exactly one imported node")
        node = imported[0]

        self.assertTrue(node.isMaterialFlagSet())  # USABLE, not merely present
        self.assertTrue(nodes.surface_terminal_wired(node),
                        "imported material would render black")

        shader = _shader_of(node)  # and the VALUES are unchanged by the round-trip
        for parm, want in SPEC.items():
            got = shader.parmTuple(parm).eval()
            expect = want if isinstance(want, tuple) else (want,)
            for g, w in zip(got, expect):
                self.assertAlmostEqual(g, w, places=5,
                                       msg="%s changed after save and load" % parm)

    def test_reimport_is_repeatable(self):
        """Importing the same asset twice yields two independent working nodes, not a collision."""
        builder = _build_material(self.staging, "twice_mat")
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, builder, "RoundTrip", "", False)
        row = self.model.find_asset_row_by_id(
            test_support.arrived(self.model, held)[0].mat_id)
        for _ in range(2):
            ok, reason, _created = material_actions.import_asset_to_scene(self.model,
                self.model.index(row, 0), target="mat"
            )
            self.assertTrue(ok, reason)
        fresh = [n for n in hou.node("/mat").children()
                 if n not in self._mat_before]
        self.assertEqual(len(fresh), 2)
        for node in fresh:
            self.assertTrue(nodes.surface_terminal_wired(node))

    @unittest.skipUnless(sys.platform != "win32",  # -- the failure cases --
                         "chmod cannot make a directory unwritable on "
                         "Windows - the failure this test injects does "
                         "not happen there")
    def test_failed_save_leaves_no_extra_row(self):
        """A save whose file write fails registers no row; skipped on Windows (no chmod) ▸r/platform-files"""
        rows_before = self.model.rowCount()
        index_path = os.path.join(self.prefs.dir, MATERIALS)
        index_before = open(index_path, "rb").read()

        mats_dir = material.section_folder(self.prefs.dir, MATERIALS)
        builder = _build_material(self.staging, "doomed_mat")
        os.chmod(mats_dir, stat.S_IRUSR | stat.S_IXUSR)   # no write
        self.addCleanup(os.chmod, mats_dir,
                        stat.S_IRWXU)                     # restore
        try:
            try:
                material_actions.add_asset(self.model, builder, "RoundTrip", "", False)
            except (OSError, hou.Error):
                pass          # raising is acceptable; registering is not
        finally:
            os.chmod(mats_dir, stat.S_IRWXU)

        self.assertEqual(self.model.rowCount(), rows_before,
                         "failed save added a row for nothing saved")
        self.assertEqual(open(index_path, "rb").read(), index_before,
                         "failed save rewrote the materials database")
        self.assertIsNone(builder.userData("assetlib_id"),
                          "failed save set the asset id on the node")

    def test_missing_mat_file_import_fails_cleanly(self):
        """An index row whose .mat is gone fails to import with a reason and leaves no nodes in /mat."""
        builder = _build_material(self.staging, "vanishing_mat")
        held = test_support.asset_ids(self.model)
        material_actions.add_asset(self.model, builder, "RoundTrip", "", False)
        mat_id = str(test_support.arrived(self.model, held)[0].mat_id)
        row = self.model.find_asset_row_by_id(mat_id)
        os.remove(material.payload_path(self.prefs, mat_id, self.prefs.ext, MATERIALS))
        ok, reason, _created = material_actions.import_asset_to_scene(self.model,
            self.model.index(row, 0), target="mat"
        )
        self.assertFalse(ok)
        self.assertTrue(reason.strip(), "the failed import returned no reason")
        fresh = [n for n in hou.node("/mat").children()
                 if n not in self._mat_before
                 and n.userData("assetlib_id") == mat_id]
        self.assertEqual(fresh, [], "failed import left nodes in /mat")


class EveryMaterialSaveIsOneSave(unittest.TestCase):
    """One method writes every renderer's material files, the COP save its own ▸p/source-derived-tests"""

    def test_one_method_writes_the_pair(self):
        import ast
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "render", "nodes.py")
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        writers = sorted(
            func.name for func in ast.walk(tree)
            if isinstance(func, ast.FunctionDef)
            and any(isinstance(call, ast.Call)
                    and getattr(call.func, "attr", "") == "save_asset_pair"
                    for call in ast.walk(func)))
        self.assertEqual(
            ["_save_copy", "save_node_cop"], writers,
            "a material save writes its files outside `_save_copy`, so its copy, "
            "adoption or thumbnail can differ from every other renderer's")


class ARedshiftImportReadsItsInterfaceOnce(unittest.TestCase):
    """A Redshift or Octane import reads its `<id>.json` once, and logs its routing only when on."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.row = next(r for r, a in enumerate(self.model.assets)
                        if a.name == "Metal")

    def _import(self, renderer):
        """Import the fixture's Metal as `renderer` into /mat; returns its `<id>.json` read count."""
        asset = self.model.assets[self.row]
        asset.renderer = renderer
        record = asset.mat_id + ".json"
        reads = []
        real_open = open

        def counting_open(path, *args, **kwargs):
            if os.path.basename(str(path)) in (record, asset.mat_id + ".interface"):
                reads.append(path)
            return real_open(path, *args, **kwargs)

        with mock.patch.object(nodes, "open", counting_open, create=True), \
                mock.patch.object(material_files, "open", counting_open, create=True), \
                mock.patch.object(asset_record, "open", counting_open, create=True):
            ok, reason, created = material_actions.import_asset_to_scene(self.model,
                self.model.index(self.row, 0), target="mat")
        for node in created:
            self.addCleanup(node.destroy)
        self.assertTrue(ok, reason)
        return len(reads)

    def test_each_renderer_reads_the_interface_once(self):
        for renderer in ("Redshift", "Octane"):
            with self.subTest(renderer=renderer):
                self.assertEqual(1, self._import(renderer),
                                 "the import re-read its builder record")


class TestUnsafeAssetIds(unittest.TestCase):
    """An id from a database becomes a filename: the shape check and the containment are tested."""

    def test_is_safe_asset_id_accepts_the_real_shapes_and_rejects_traversal(self):
        """Tests the check: "32 hex only" would reject the fixture's legacy timestamp ids and "-1"."""
        for good in ("00755b7004824333af08d921462fa3ae",
                     "139888336268658010", "-1", "a", "A_b-c.d"):
            self.assertTrue(material.is_safe_asset_id(good), good)
        for bad in ("../../.ssh/authorized_keys", "..", ".",
                    "a/b", "a\\b", "", "x" * 65, "a b", "a\x00b"):
            self.assertFalse(material.is_safe_asset_id(bad), repr(bad))

    def test_contained_join_raises_on_an_escape_and_a_symlink_out(self):
        """The symlink the shape check cannot see: a clean id, and a link placed in the asset folder."""
        base = tempfile.mkdtemp(prefix="amaze_contain_")
        self.addCleanup(shutil.rmtree, base, True)
        inside = hostos.contained_join(base, "materials/", "asset.mat")
        self.assertTrue(inside.startswith(base))
        with self.assertRaises(hostos.PathOutsideBase):
            hostos.contained_join(base, "materials/", "../../escaped.mat")
        outside = tempfile.mkdtemp(prefix="amaze_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        os.makedirs(os.path.join(base, "materials"))
        os.symlink(outside, os.path.join(base, "materials", "away"))
        with self.assertRaises(hostos.PathOutsideBase):
            hostos.contained_join(base, "materials", "away", "asset.mat")

    def test_payload_path_composes_with_or_without_a_separator_and_contains(self):
        """Concatenation gave `<lib>mat/abc.mat` for a dir saved without its separator."""
        base = tempfile.mkdtemp(prefix="amaze_payload_")
        self.addCleanup(shutil.rmtree, base, True)

        class _P:
            ext = ".mat"
            dir = base + os.sep

        for section, folder in ((MATERIALS, "materials"), (library_files.NODES, "nodes")):
            for suffix in (_P.ext, ".json", "_cop" + _P.ext):
                self.assertEqual(
                    os.path.normpath(os.path.join(base, folder, "abc" + suffix)),
                    os.path.normpath(material.payload_path(_P, "abc", suffix, section)),
                    "payload_path put %r outside its section folder" % suffix)

        class _Unslashed(_P):
            dir = base                      # no trailing separator

        self.assertEqual(
            os.path.normpath(os.path.join(base, "materials", "abc.mat")),
            os.path.normpath(material.payload_path(_Unslashed, "abc",
                                                   ".mat", MATERIALS)),
            "a library path without its trailing separator composed "
            "wrong - which is what concatenation did here")
        with self.assertRaises(hostos.PathOutsideBase):    # the PATH check, next to the RECORD's
            material.payload_path(_P, "../../.ssh/authorized_keys", ".mat", MATERIALS)

    def test_nothing_is_read_from_the_old_shared_folder(self):
        """Only the converter reads format 3's `mat/`; a path is always in the section folder."""
        base = tempfile.mkdtemp(prefix="amaze_payload_legacy_")
        self.addCleanup(shutil.rmtree, base, True)

        class _P:
            dir = base + os.sep

        os.makedirs(os.path.join(base, "mat"))
        with open(os.path.join(base, "mat", "old.mat"), "w", encoding="utf-8") as handle:
            handle.write("nodes\n")
        self.assertEqual(
            os.path.join(base, "materials", "old.mat"),
            os.path.normpath(material.payload_path(_P, "old", ".mat", MATERIALS)),
            "a path fell back to format 3's shared folder")

    def test_an_import_with_a_traversal_id_creates_nothing(self):
        """End to end: a traversal id is refused by name, nothing is created, the file is never opened."""
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

        index_path = os.path.join(prefs_obj.dir, MATERIALS)
        with open(index_path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["assets"]["../../.ssh/authorized_keys"] = dict(
            data["assets"].pop("-1"), id="../../.ssh/authorized_keys", name="tampered")
        with open(index_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        row = model.find_asset_row_by_id("../../.ssh/authorized_keys")
        self.assertNotEqual(row, -1, "premise: the tampered row loaded")

        before = set(hou.node("/mat").children())
        ok, reason, _created = material_actions.import_asset_to_scene(model, model.index(row, 0),
                                                 target="mat")
        self.assertFalse(ok, "a traversal id was imported")
        self.assertIn("tampered", reason)
        self.assertEqual(before, set(hou.node("/mat").children()),
                         "a refused import still created a node")


class TestInterfaceIsNeverExecuted(unittest.TestCase):
    """`.interface` is code chosen by an id; it is read by regex, never executed ▸r/interface-contents"""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

    def test_payload_in_an_interface_file_does_not_run(self):
        marker = os.path.join(tempfile.mkdtemp(prefix="amaze_exec_"), "ran")
        self.addCleanup(shutil.rmtree, os.path.dirname(marker), True)

        from amaze.core import library_conversion
        payload = ("import pathlib\n"
                   "pathlib.Path(%r).write_text('executed')\n"
                   "hou_node = hou_parent.createNode('subnet')\n" % marker).encode("utf-8")
        self.assertEqual("subnet", library_conversion.interface_type(payload))
        self.assertEqual("subnet", library_conversion.builder_from_members(
            {"interface": payload})["type"], "an old package's interface member was not read")
        row = next(r for r in range(self.model.rowCount())
                   if str(self.model.assets[r].renderer))
        asset = self.model.assets[row]
        record = asset_record.path_for(self.prefs, asset.mat_id, MATERIALS)
        os.remove(record)    # no `<id>.json`: an import has no builder and reads nothing else
        with open(os.path.join(os.path.dirname(record), asset.mat_id + ".interface"), "wb") as fh:
            fh.write(payload)
        material_actions.import_asset_to_scene(self.model, self.model.index(row, 0), target="mat")  # succeed or refuse; only the payload running fails, so do not assert it imports
        self.assertFalse(
            os.path.exists(marker),
            "the .interface file was EXECUTED - the import path is running "
            "code out of a file the library index chose")

    def test_a_sidecar_round_trips_interface_and_values(self):
        """What the sidecar must keep, checked by capture and then restore."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")

        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_probe", "Probe", 1,
                                           default_value=(0.25,)))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_probe").set(0.75)

        captured = nodes.capture_builder(builder)
        self.assertIn("amaze_probe", captured["interface"])
        self.assertEqual({"val": 0.75}, captured["values"].get("amaze_probe"))
        json.dumps(captured)    # the section is written as JSON, so it must serialise

        fresh = staging.createNode("subnet")
        self.assertIsNone(fresh.parm("amaze_probe"),
                          "premise: the spare parm is not there by default")
        nodes.apply_builder(fresh, captured)
        self.assertIsNotNone(fresh.parm("amaze_probe"),
                             "the sidecar did not restore the interface")
        self.assertAlmostEqual(0.75, fresh.parm("amaze_probe").eval(), 5,
                               "the sidecar restored the parm but not its "
                               "value")

    def _animated_builder(self):
        """A builder with a Python expression and two parms keyed at frames 1 and 25."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")
        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_py", "Py", 1))
        group.append(hou.FloatParmTemplate("amaze_keyed", "Keyed", 1))
        group.append(hou.StringParmTemplate("amaze_skeyed", "SKeyed", 1))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_py").setExpression("hou.frame() * 3", language=hou.exprLanguage.Python)
        keys = []
        for frame, value in ((1, 0.0), (25, 10.0)):
            key = hou.Keyframe()
            key.setFrame(frame)
            key.setValue(value)
            key.setExpression("linear()", hou.exprLanguage.Hscript)
            keys.append(key)
        builder.parm("amaze_keyed").setKeyframes(keys)
        skeys = []
        for frame, text in ((1, "'early'"), (25, "'late'")):
            key = hou.StringKeyframe()
            key.setFrame(frame)
            key.setExpression(text, hou.exprLanguage.Python)
            skeys.append(key)
        builder.parm("amaze_skeyed").setKeyframes(skeys)
        return staging, builder

    def test_an_expression_keeps_its_language_and_keys_stay_keys(self):
        """`setExpression` without a language reads Python as HScript; several keys are no expression."""
        staging, builder = self._animated_builder()
        self.addCleanup(hou.setFrame, hou.frame())
        captured = nodes.capture_builder(builder)
        fresh = staging.createNode("subnet")
        nodes.apply_builder(fresh, captured)
        py = fresh.parm("amaze_py")
        self.assertEqual(hou.exprLanguage.Python, py.expressionLanguage(),
                         "a Python expression came back in another language")
        hou.setFrame(2)
        self.assertAlmostEqual(6.0, py.eval(), 5)
        keyed = fresh.parm("amaze_keyed")
        self.assertEqual(2, len(keyed.keyframes()),
                         "the keyframes came back baked to one value")
        hou.setFrame(13)
        self.assertAlmostEqual(5.0, keyed.eval(), 4)
        skeyed = fresh.parm("amaze_skeyed")
        self.assertEqual(2, len(skeyed.keyframes()), "the string keys were lost")
        hou.setFrame(30)
        self.assertEqual("late", skeyed.eval())

    def test_a_sidecar_stays_readable_on_both_sides_of_the_keyframe_change(self):
        """An old sidecar loads as before, and every new value still has a field an old reader reads."""
        staging, builder = self._animated_builder()
        for name, spec in nodes.capture_builder(builder)["values"].items():
            self.assertTrue({"expr", "str", "val"} & set(spec),
                            "%s has nothing an older Amaze can apply: %r" % (name, spec))
        old = {"dialog_script": builder.parmTemplateGroup().asDialogScript(),
               "values": {"amaze_keyed": {"expr": "$F * 2"}, "amaze_py": {"val": 0.5}}}
        fresh = staging.createNode("subnet")
        from amaze.core import library_conversion    # an old sidecar is read by the converter
        nodes.apply_builder(fresh, library_conversion.builder_from_bytes(
            json.dumps(old).encode("utf-8"), lambda: b""))
        self.assertEqual("$F * 2", fresh.parm("amaze_keyed").expression())
        self.assertEqual(hou.exprLanguage.Hscript, fresh.parm("amaze_keyed").expressionLanguage())
        self.assertAlmostEqual(0.5, fresh.parm("amaze_py").eval(), 5)

    def test_a_promoted_RAMP_round_trips_through_its_components(self):
        """A promoted ramp round-trips: shape from the dialog script, values from its Float components."""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")

        group = builder.parmTemplateGroup()
        group.append(hou.RampParmTemplate("amaze_ramp", "Ramp",
                                          hou.rampParmType.Float))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_ramp").set(
            hou.Ramp((hou.rampBasis.Linear, hou.rampBasis.Linear),
                     (0.0, 1.0), (0.2, 0.9)))

        document = nodes.capture_builder(builder)          # must not raise
        json.dumps(document)
        self.assertIn(
            "amaze_ramp", document["interface"],
            "the ramp's shape is not in the captured interface")
        self.assertTrue(
            [k for k in document["values"] if k.startswith("amaze_ramp")],
            "no ramp component value was captured, so an edited ramp "
            "comes back at its default: %s" % sorted(document["values"]))

        fresh = staging.createNode("subnet")
        nodes.apply_builder(fresh, document)
        restored = fresh.parm("amaze_ramp")
        self.assertIsNotNone(restored,
                             "the sidecar did not restore the ramp")
        self.assertAlmostEqual(
            0.9, restored.evalAsRamp().lookup(1.0), 5,
            "the ramp came back at its default value")

    def test_a_value_the_sidecar_cannot_serialise_loses_only_that_parm(self):
        """A value the sidecar cannot serialise loses only that parm, never the asset ▸p/asset-write-unit"""
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        builder = staging.createNode("subnet")
        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_keeps", "Keeps", 1,
                                           default_value=(0.25,)))
        builder.setParmTemplateGroup(group)
        builder.parm("amaze_keeps").set(0.75)

        from unittest.mock import patch

        real_eval = hou.Parm.eval

        def unserialisable_eval(self):
            if self.name() == "amaze_keeps":
                return object()          # nothing json can serialise
            return real_eval(self)

        with patch.object(hou.Parm, "eval", unserialisable_eval):
            captured = nodes.capture_builder(builder)      # must not raise
        self.assertNotIn(
            "amaze_keeps", captured["values"],
            "the unserialisable parm was captured anyway")

    def test_an_absent_sidecar_is_not_an_error(self):
        """Assets saved before the sidecar format have none; the loader returns {} instead of failing."""
        self.assertEqual({}, asset_record.saved_builder(self.prefs, "does-not-exist", MATERIALS))
        from amaze.core import library_conversion
        self.assertEqual({}, library_conversion.builder_from_bytes(b"", lambda: b""))
        with test_support.captured_log() as log:
            self.assertEqual({}, library_conversion.builder_from_bytes(
                b"{not json at all", lambda: b"", where="broken"))
        self.assertTrue(log.matching("builder sidecar unreadable", "convert"),
                        "a damaged sidecar was not logged")
        record = os.path.join(self.prefs.dir, "broken.json")
        with open(record, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        with test_support.captured_log() as log:
            self.assertEqual({"metadata": {}, "builder": {}}, asset_record.read(record))
        self.assertTrue(log.matching("asset record corrupt/unreadable", "library"),
                        "a damaged <id>.json was not logged")


class UpdateExistingIsGuardedAgainstTheOtherSessionTest(unittest.TestCase):
    """Two structural updates to one id from two sessions must not silently overwrite each other."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node checks $OCIO; nothing renders here
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def _their_write(self, mat_id):
        """Another session replaces the .mat underneath this one."""
        path = self.model.asset_files(mat_id)["mat"]
        with open(path, "ab") as fh:
            fh.write(b"\0their-bytes")
        stat = os.stat(path)
        os.utime(path, ns=(stat.st_atime_ns,
                           stat.st_mtime_ns + 5_000_000_000))

    def test_a_changed_mat_raises_update_refused(self):
        row = next(r for r in range(self.model.rowCount())
                   if str(self.model.assets[r].renderer))
        mat = self.model.assets[row]
        before = open(self.model.asset_files(mat.mat_id)["mat"],
                      "rb").read()
        self._their_write(mat.mat_id)
        theirs = open(self.model.asset_files(mat.mat_id)["mat"],
                      "rb").read()

        node = self.staging.createNode("subnet")
        with test_support.captured_log() as log, \
                self.assertRaises(material_actions.UpdateRefused,
                                  msg="the update overwrote content another session "
                                      "wrote since this one read it") as refused:
            material_actions.update_asset_content(self.model, row, node)

        self.assertEqual(messages.UPDATE_REFUSED_CHANGED_ON_DISK, str(refused.exception))
        self.assertEqual([], log.messages("alert"),
                         "the refusal raised its own alert besides the save's one message")
        now = open(self.model.asset_files(mat.mat_id)["mat"],
                   "rb").read()
        self.assertEqual(theirs, now,
                         "the refusal still modified their file")
        self.assertNotEqual(before, now, "premise check")

    def test_our_own_update_rebaselines(self):
        """A session's own write must not fail its own check: two updates in a row are ordinary use."""
        row = next(r for r in range(self.model.rowCount())  # the stored value may be MaterialX
                   if renderers.is_karma(
                       self.model.assets[r].renderer))
        node = _build_material(self.staging, "update_guard_probe")
        first = material_actions.update_asset_content(self.model, row, node)
        self.assertTrue(first, "premise: the first update succeeds")
        second = material_actions.update_asset_content(self.model, row, node)
        self.assertTrue(second,
                        "a session's own write failed its own check - "
                        "the baseline was not refreshed")


class AStaleCompanionIsRemovedWhateverTheExtension(unittest.TestCase):

    def test_an_update_with_no_cop_net_removes_the_companion(self):
        """The companion's name follows the extension preference, as every other asset file does."""
        test_support.pin_env(self, "OCIO", "/dev/null")
        prefs = test_support.fixture_prefs(self)
        prefs._ext = ".cpio"
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs)
        staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(staging.destroy)
        row = next(r for r in range(model.rowCount())
                   if renderers.is_karma(model.assets[r].renderer))
        companion = model.asset_files(model.assets[row].mat_id)["cop"]
        self.assertTrue(companion.endswith("_cop.cpio"), companion)
        with open(companion, "w", encoding="utf-8") as handle:
            handle.write("a companion the new network no longer uses")
        node = _build_material(staging, "stale_companion_probe")
        self.assertTrue(material_actions.update_asset_content(model, row, node),
                        "premise: the update succeeds")
        self.assertFalse(os.path.exists(companion),
                         "the stale companion was left next to the asset")


class AnUpdateWhoseListWriteFails(unittest.TestCase):
    """The files are new, the record stays in memory, and the save's own alert is the only dialog."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def _listed(self, mat_id):
        with open(self._index(), encoding="utf-8") as handle:
            return json.load(handle)["assets"][mat_id]

    def _index(self):
        return os.path.join(self.prefs.dir, self.model.DB_FILENAME)

    def test_the_return_value_reports_it_and_the_next_save_writes_the_record(self):
        row = next(r for r in range(self.model.rowCount())
                   if renderers.is_karma(self.model.assets[r].renderer))
        mat = self.model.assets[row]
        mat_id = str(mat.mat_id)
        network = self.model.asset_files(mat_id)["mat"]
        with open(network, "rb") as handle:
            before = handle.read()
        listed = self._listed(mat_id)
        node = _build_material(self.staging, "refused_list_probe")
        with test_support.full_disk_for(self._index()), test_support.captured_log() as log:
            answer = material_actions.update_asset_content(self.model, row, node)
        with open(network, "rb") as handle:
            self.assertNotEqual(before, handle.read(), "premise: the update wrote no files")
        self.assertEqual(listed, self._listed(mat_id), "premise: the list write went through")
        self.assertNotEqual(listed["date"], mat.date, "premise: the record kept its date")
        self.assertTrue(answer, "the files are new, yet the update returned that nothing was "
                        "written, which the panel shows as Update failed")
        self.assertEqual(1, len(log.messages("alert")),
                         "a second alert followed the save's own: %s" % log.messages("alert"))
        self.assertTrue(log.matching("could not save the library", "alert"),
                        log.messages("alert"))
        from amaze.core import library_db
        self.assertTrue(library_db.document(self.prefs, self.model.DB_FILENAME).dirty,
                        "the refused record was dropped, not kept for the next save")
        library_db.flush()
        self.assertEqual(mat.date, self._listed(mat_id)["date"],
                         "the next save that works did not write the update's record")


class AnAddWhoseListWriteFails(unittest.TestCase):
    """A material whose list write fails: no tile, no files, returns False, at most one alert."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_nothing_is_added_and_it_returns_false(self):
        node = _build_material(self.staging, "refused_add_probe")
        held = test_support.asset_ids(self.model)
        index = os.path.join(self.prefs.dir, self.model.DB_FILENAME)
        folder = material.section_folder(self.prefs.dir, MATERIALS)
        files = sorted(os.listdir(folder))
        with test_support.full_disk_for(index), test_support.captured_log() as log:
            answer = material_actions.add_asset(self.model, node, "", "", False)
        self.assertEqual([], test_support.arrived(self.model, held),
                         "a material whose row was refused shows as a tile")
        self.assertFalse(answer, "the add returned success while nothing was saved")
        self.assertEqual(files, sorted(os.listdir(folder)),
                         "a material whose row was refused left its files")
        self.assertLessEqual(len(log.messages("alert")), 1,
                             "a second alert followed the library's own: %s" % log.messages("alert"))


class StructureSignatureTest(unittest.TestCase):
    """Versions rule: only values differ means a new version, else structural ▸p/structure-signature"""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_value_edits_and_layout_moves_keep_the_signature(self):
        builder = _build_material(self.staging, "sig_keep_probe")
        before = nodes.structure_signature(builder)
        shader = _shader_of(builder)
        scalar = next(parm for parm in shader.parms()    # a SCALAR float: a colour's .parm() is None
                      if parm.parmTemplate().numComponents() == 1
                      and parm.parmTemplate().type()
                      == hou.parmTemplateType.Float)
        scalar.set(scalar.eval() + 0.111)
        self.assertEqual(before, nodes.structure_signature(builder),
                         "a value edit changed the structure signature - "
                         "every parameter change would take the structural "
                         "path and Versions would never be used")
        for child in builder.children():
            child.move(hou.Vector2(3.0, -2.0))
        self.assertEqual(before, nodes.structure_signature(builder),
                         "node positions changed the signature")

    def test_an_added_node_or_a_rewire_changes_it(self):
        builder = _build_material(self.staging, "sig_change_probe")
        before = nodes.structure_signature(builder)
        image = builder.createNode("mtlximage", "sig_added")
        added = nodes.structure_signature(builder)
        self.assertNotEqual(before, added,
                            "an added node did not change the signature - "
                            "a structural edit would silently become a "
                            "version")
        _shader_of(builder).setInput(0, image)
        self.assertNotEqual(added, nodes.structure_signature(builder),
                            "a rewire did not change the signature")

    def test_staged_asset_loads_and_cleans_up_even_when_the_loader_raises(self):
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(r for r in range(model.rowCount())
                   if renderers.is_karma(model.assets[r].renderer))
        mat = model.assets[row]
        obj_before = set(hou.node("/obj").children())
        signature = nodes.staged_asset(self.prefs, mat,
                                       nodes.structure_signature)
        self.assertTrue(signature and len(signature) == 16)
        self.assertEqual(obj_before, set(hou.node("/obj").children()),
                         "staged_asset left its staging network in /obj")

        def boom(_node):
            raise RuntimeError("loader failure")

        with self.assertRaises(RuntimeError):
            nodes.staged_asset(self.prefs, mat, boom)
        self.assertEqual(obj_before, set(hou.node("/obj").children()),
                         "a raising loader left the staging network in /obj")


class AnUnreadablePayloadFailsWithoutADialogTest(unittest.TestCase):
    """An unreadable payload fails with a reason, never a dialog with no UI ▸r/status-bar"""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def test_a_missing_payload_returns_a_reason_not_an_OSError(self):
        """The contract the callers are written against: a reason string, never a raise."""
        missing = os.path.join(self.prefs.dir, "no-such-asset.mat")
        self.assertFalse(os.path.exists(missing))
        problem = nodes.load_items_strict(self.staging, missing)
        self.assertTrue(problem, "an unreadable payload reported nothing, so "
                                 "the caller cannot tell it apart from a "
                                 "clean load")
        self.assertIn("could not be read", problem)
        as_dir = os.path.join(self.prefs.dir, "payload-is-a-directory.mat")    # getsize RETURNS a size for a folder
        os.makedirs(as_dir, exist_ok=True)
        self.addCleanup(os.rmdir, as_dir)
        problem = nodes.load_items_strict(self.staging, as_dir)
        self.assertTrue(problem, "a directory in the payload slot loaded as "
                                 "if it were a material")
        self.assertIn(
            os.path.basename(as_dir), problem,
            "the reason does not name the file, so the reader gets only "
            "Houdini's own message: %r" % problem)

    def test_both_imports_raise_hou_error_with_no_ui_present(self):
        """Headless, a missing payload is a hou.Error with a reason, never a dialog's AttributeError."""
        self.assertFalse(hasattr(hou, "ui"),
                         "this test needs a headless hou to test anything")
        for method in ("load_items_file", "load_items_file_mtlx"):
            with self.subTest(method):
                handler = nodes.NodeHandler(self.prefs)
                handler._builder_node = self.staging
                mat = material.Material(name="gone", mat_id="no-such-asset-id")
                with self.assertRaises(hou.Error) as caught:
                    getattr(handler, method)(mat)
                self.assertIn("could not be read", str(caught.exception))

    def _assert_oserror_opens_no_dialog(self, method: str):
        """Raise the OSError the callers catch: their handler must not open a dialog."""
        handler = nodes.NodeHandler(self.prefs)
        handler._builder_node = self.staging
        mat = material.Material(name="gone", mat_id="no-such-asset-id")

        from unittest.mock import patch

        def unreadable(_node, _file_name):
            raise OSError(5, "Input/output error")

        with patch.object(nodes, "load_items_strict", unreadable):
            try:
                getattr(handler, method)(mat)
            except AttributeError as crash:
                self.fail("the error handler called hou.ui and crashed: %s"
                          % crash)
            except (OSError, hou.Error):
                return
        self.fail("%s caught a real read failure and reported nothing"
                  % method)

    def test_a_read_failure_opens_no_dialog_on_either_import(self):
        """▸r/status-bar - hou.ui does not exist headless."""
        for method in ("load_items_file", "load_items_file_mtlx"):
            with self.subTest(method):
                self._assert_oserror_opens_no_dialog(method)


class AFreshHandlerNamesNoBuilder(unittest.TestCase):
    """Before any import a handler holds no builder, so a cleanup cannot treat `/stage` as one."""

    def test_the_builder_starts_empty(self):
        handler = nodes.NodeHandler(test_support.fixture_prefs(self))
        self.assertIsNone(handler.builder_node)


class ASavedAssetRebuildsInsideAScratchNetwork(unittest.TestCase):
    """`NodeHandler.rebuild_saved` rebuilds a saved asset in a scratch network for reading."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.karma = next(
            self.model.assets[r] for r in range(self.model.rowCount())
            if renderers.is_karma(self.model.assets[r].renderer))
        with hou.undos.disabler():
            self.scratch = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.scratch.destroy)

    def test_a_karma_asset_is_built_in_the_scratch_and_an_unknown_one_raises(self):
        obj_before = set(hou.node("/obj").children())
        builder = nodes.NodeHandler(self.prefs).rebuild_saved(self.karma, self.scratch)
        self.assertEqual(self.scratch.path(), builder.parent().path())
        self.assertTrue(builder.children(), "the builder came back empty")
        self.assertEqual(obj_before, set(hou.node("/obj").children()))
        odd = material.Material(name="odd", renderer="", mat_id=self.karma.mat_id)
        with self.assertRaises(hou.OperationFailed) as caught:
            nodes.NodeHandler(self.prefs).rebuild_saved(odd, self.scratch)
        self.assertIn("unrecognised renderer", str(caught.exception))


class AnImportIsCreatedInTheNetworkTheArtistHasOpen(unittest.TestCase):
    """An auto import goes where the editor is: a Material Network open is the destination."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.addCleanup(test_support.clear_obj)
        self.mat = hou.node("/mat")
        self.stage = hou.node("/stage")
        self.geo = hou.node("/obj").createNode("geo", "routing_geo")
        made = []
        self.addCleanup(lambda: [n.destroy() for n in made if _alive(n)])
        self.library = self.stage.createNode("materiallibrary", "routing_lib")
        self.lop_matnet = self.stage.createNode("matnet", "routing_lop_matnet")
        self.builder = self.mat.createNode("subnet", "routing_builder")
        made.extend((self.library, self.lop_matnet, self.builder))

    def _routed(self, network):
        """(where an auto import into `network` goes, or the error; whether it existed already)."""
        handler = nodes.NodeHandler(self.prefs)
        handler._context_override = network
        karma = material.Material(name="routed", renderer=renderers.KARMA.key, mat_id="routed")
        ok, reason = handler.update_context(karma, "auto")
        if not ok:
            return (reason, None)
        return (handler._import_path.path(), handler._use_existing_node)

    def test_every_network_kind_routes_as_it_should(self):
        obj = hou.node("/obj")
        obj_matnet = obj.createNode("matnet", "routing_obj_matnet")
        sop_matnet = self.geo.createNode("matnet", "routing_sop_matnet")
        attribvop = self.geo.createNode("attribvop", "routing_vop")
        copnet = obj.createNode("copnet", "routing_cop")
        cases = (    # (what is open, where it goes, the container was already there)
            (obj, "/mat", True),
            (self.mat, "/mat", True),
            (obj_matnet, obj_matnet.path(), True),
            (sop_matnet, sop_matnet.path(), True),
            (copnet, "/mat", True),
            (attribvop, "/mat", True),    # VOP children, but not a Material Network
            (self.builder, "/mat", True),    # inside a builder: never a builder in a builder
            (self.lop_matnet, "/mat", True),
            (self.library, self.library.path(), True),
            (self.stage, messages.LOP_IMPORT_OUTSIDE_LIBRARY, None),
        )
        for network, where, theirs in cases:
            with self.subTest(network.path()):
                self.assertEqual((where, theirs), self._routed(network))
        empty = obj.createNode("geo", "routing_empty_geo")
        landed, theirs = self._routed(empty)    # a geo with no matnet gets ONE, made by the import
        self.assertEqual(empty.path(), hou.node(landed).parent().path())
        self.assertEqual("matnet", hou.node(landed).type().name())
        self.assertFalse(theirs)

    def test_a_karma_import_is_created_inside_the_open_matnet(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        karma = next(a for a in model.assets if renderers.is_karma(a.renderer))
        sop_matnet = self.geo.createNode("matnet", "landing_matnet")
        mat_before = set(self.mat.children())
        ok, reason, created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            karma, context_node=sop_matnet)
        self.assertTrue(ok, reason)
        self.assertEqual([sop_matnet.path()], [c.parent().path() for c in created])
        self.assertEqual(mat_before, set(self.mat.children()),
                         "the import went to /mat with a Material Network open")

    def test_the_online_import_and_generate_use_the_open_matnet_too(self):
        sop_matnet = self.geo.createNode("matnet", "destination_matnet")
        for network, where in ((sop_matnet, sop_matnet), (self.geo, self.mat),
                               (hou.node("/obj"), self.mat)):
            with self.subTest(network.path()), mock.patch.object(
                    nodes.NodeHandler, "get_current_network_node", return_value=network):
                self.assertEqual(where, nodes.karma_destination(self.prefs))


class TheBuilderTypeIsReadFromTheRecordFirst(unittest.TestCase):
    """`<id>.json` names the builder; the converter reads format 3's sidecar, then `.interface`."""

    INTERFACE = "node = hou_parent.createNode('subnet', 'x')\n"

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.asset = next(a for a in self.model.assets if renderers.is_karma(a.renderer))
        self.record = asset_record.path_for(self.prefs, self.asset.mat_id, MATERIALS)
        folder = os.path.dirname(self.record)
        self.sidecar = os.path.join(folder, self.asset.mat_id + ".builder.json")
        self.iface = os.path.join(folder, self.asset.mat_id + ".interface")

    def _type(self):
        return material_files.get_saved_node_type(self.prefs, self.asset, MATERIALS)

    def _write(self, path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _make_format_3(self):
        """The asset as an unconverted library holds it: no `<id>.json`, an `.interface`."""
        os.remove(self.record)
        self._write(self.iface, self.INTERFACE)

    def _converted_type(self, sidecar=None, stale=False, interface=INTERFACE):
        """The type the converter reads from format 3's sidecar bytes and `.interface`."""
        from amaze.core import library_conversion
        raw = sidecar.encode("utf-8") if sidecar is not None else b""
        return library_conversion.builder_from_bytes(
            raw, lambda: interface.encode("utf-8"), stale).get("type", "")

    def test_format_3_files_alone_name_no_builder(self):
        """No fallback: an asset without `<id>.json` has no builder until converted."""
        self._make_format_3()
        self._write(self.sidecar, json.dumps({"type": "x", "dialog_script": ""}))
        self.assertEqual("", self._type(), "a format 3 file was read outside the converter")

    def test_the_record_names_the_builder(self):
        usd = renderers.REDSHIFT.usd_builder
        self.assertEqual("subnet", self._type(), "premise: the fixture's record names a subnet")
        asset_record.write_section(self.record, asset_record.BUILDER,
                                   {"type": usd, "interface": "", "values": {}})
        self.assertEqual(usd, self._type())
        self.assertTrue(self.model.is_usd_material(self.asset))

    def test_an_unusable_record_names_no_builder(self):
        for unusable in ("not json", json.dumps(["a list"]),
                         json.dumps({"builder": {"type": ""}}),
                         json.dumps({"builder": {"type": 7}})):
            with self.subTest(unusable):
                self._write(self.record, unusable)
                self.assertEqual("", self._type())

    def test_the_converter_takes_the_sidecar_and_falls_back_to_the_interface(self):
        usd = renderers.REDSHIFT.usd_builder
        self.assertEqual("subnet", self._converted_type(), "premise: the .interface names a subnet")
        self.assertEqual(usd, self._converted_type(json.dumps(
            {"format": 1, "type": usd, "dialog_script": "", "values": {}})))
        for unusable in ("not json", json.dumps(["a list"]), json.dumps({"type": ""}),
                         json.dumps({"type": 7})):
            with self.subTest(unusable):
                self.assertEqual("subnet", self._converted_type(unusable))

    def test_the_converter_ignores_a_sidecar_older_than_its_interface(self):
        """An Amaze that wrote no sidecar re-saved the asset: the newer .interface is used."""
        sidecar = json.dumps({"type": renderers.REDSHIFT.usd_builder, "dialog_script": ""})
        self.assertEqual("subnet", self._converted_type(sidecar, stale=True))

    def test_a_linked_record_is_not_followed(self):
        if not (hasattr(os, "symlink") and getattr(os, "O_NOFOLLOW", 0)):
            self.skipTest("no symlinks here")
        outside = os.path.join(self.prefs.path, "elsewhere.json")
        self._write(outside, json.dumps({"builder": {"type": "rs_usd_material_builder"}}))
        os.remove(self.record)
        os.symlink(outside, self.record)
        self.assertEqual("", self._type(), "a linked <id>.json was followed out of the library")

    def test_a_long_preamble_still_reads(self):
        self.assertEqual("subnet", self._converted_type(
            interface="#" * 9000 + "\n" + self.INTERFACE))


class ALooseKarmaLoadKeepsItsArrangement(unittest.TestCase):
    """Saved nodes keep their positions; only the connectors Amaze adds are placed, next to them."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.network = hou.node("/mat").createNode("subnet", "loose_layout_home")
        self.addCleanup(self.network.destroy)

    def test_the_saved_nodes_keep_their_positions_and_new_nodes_go_beside_them(self):
        image = self.network.createNode("mtlximage", "layout_image")
        surface = self.network.createNode("mtlxstandard_surface", "layout_surface")
        surface.setInput(surface.inputIndex("base_color"), image)
        image.setPosition(hou.Vector2(10.0, 10.0))
        surface.setPosition(hou.Vector2(13.0, 8.0))
        handler = nodes.NodeHandler(self.prefs)
        handler._renderer = renderers.KARMA.key
        self.assertTrue(handler.save_node(surface, "looselayout", False), "premise: no save")
        asset = material.Material(name="looselayout", renderer=renderers.KARMA.key,
                                  mat_id="looselayout")
        ok, reason, created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            asset, context_node=self.network)
        self.assertTrue(ok, reason)
        builder, = created
        self.addCleanup(builder.destroy)
        loaded = [c for c in builder.children() if c.type().name().startswith("mtlx")]
        plumbing = [c for c in builder.children() if c not in loaded]
        self.assertEqual(2, len(loaded), "premise: the loose save came back loose")
        self.assertTrue(plumbing, "premise: the builder has its own connectors")
        by_type = {c.type().name(): c for c in loaded}
        offset = (by_type["mtlxstandard_surface"].position()
                  - by_type["mtlximage"].position())
        self.assertEqual((3.0, -2.0), (round(offset.x(), 4), round(offset.y(), 4)),
                         "the saved nodes were moved")
        self.assertEqual([], [(p.name(), n.name()) for p in plumbing for n in loaded
                              if _overlap(p, n)], "a connector was placed on a saved node")
        right = max(n.position().x() + n.size().x() for n in loaded)
        outputs = [p for p in plumbing if p.type().name() != "subinput"]
        self.assertEqual([], [p.name() for p in outputs if p.position().x() < right],
                         "an output connector is not to the right of what feeds it")


def _overlap(a, b) -> bool:
    (ax, ay), (aw, ah) = a.position(), a.size()
    (bx, by), (bw, bh) = b.position(), b.size()
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _alive(node) -> bool:
    try:
        node.path()
        return True
    except hou.ObjectWasDeleted:
        return False


if __name__ == "__main__":
    unittest.main()
