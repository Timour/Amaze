"""File section: prefs migration, tab intro, `kind_for` routing, Copy Path, OS icon, hip drag."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.actions import files as files_actions  # noqa: E402
from amaze import messages  # noqa: E402
from amaze.core import debug, file_library, geo_library, scene_captures  # noqa: E402
from amaze.core import locations as locations_mod  # noqa: E402
from amaze.core import library_files, tile_icons  # noqa: E402
from amaze.helpers import helpers, hostos  # noqa: E402
from amaze.panel import delegates  # noqa: E402
from amaze.prefs import prefs as prefs_module  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the log


def _prefs_with_settings(testcase, settings: dict, tag_favourites=True):
    """A Prefs loaded from `settings`; `library_user` goes in the file, as load() reads it off disk."""
    home = tempfile.mkdtemp(prefix="amaze_file_prefs_")
    testcase.addCleanup(shutil.rmtree, home, ignore_errors=True)
    settings = dict(settings)
    settings.setdefault("library_user", test_support.FIXTURE_USER)
    with open(os.path.join(home, "settings.json"), "w",
              encoding="utf-8") as handle:
        json.dump(settings, handle)
    p = prefs_module.Prefs()
    p.path = home
    p.load()
    return p


def _location_prefs(testcase, settings, tag_favourites=True):
    """A Prefs over a fresh temp library, set before load() because the first read migrates."""
    library = tempfile.mkdtemp(prefix="amaze_loc_library_")
    testcase.addCleanup(shutil.rmtree, library, ignore_errors=True)
    data = dict(settings)
    data["directory"] = library
    locations_mod.forget()
    testcase.addCleanup(locations_mod.forget)
    prefs = _prefs_with_settings(testcase, data,
                                 tag_favourites=tag_favourites)
    library = prefs.dir    # load() normalises the path; compare the resolved form
    testcase.assertTrue(
        os.path.normcase(os.path.normpath(library)).startswith(    # normcase+normpath both sides: prefs.dir is Houdini-spelled, gettempdir() native
            os.path.normcase(os.path.normpath(tempfile.gettempdir()))),
        "the fixture is pointed at %r" % (library,))
    return prefs, library


class TheFileTabIsAddedOnceTest(unittest.TestCase):
    """A settings file from before the File section gets the tab once; turning it off is then kept."""

    def test_the_file_tab_is_added_once_and_stays_off_when_disabled(self):
        old = {"enabled_sections": ["material", "code"]}
        p = _prefs_with_settings(self, old)
        self.assertIn("file", p.enabled_sections,
                      "existing users never see the File tab")
        # Turning it off then stays off, because the seen-marker is kept.
        p.enabled_sections = ["material", "code"]
        p.save()
        q = prefs_module.Prefs()
        q.path = p.path
        q.load()
        self.assertNotIn(
            "file", q.enabled_sections,
            "disabling the File tab is not kept - the tab is added "
            "again on every launch")


class LocationsLiveInTheFilesDatabaseTest(unittest.TestCase):
    """Each user's locations are their own records in files.json, keyed by the location's id."""

    REAL_SHAPE = {
        "directory": "",
        "file_folders": ["/tex/img/", "/tex/bokeh/", "/photo/2023/",
                         "/models/obj/", "/houdini/exercise/", "/tex/hdr/"],
        "file_favorites": ["/tex/hdr/017.hdr", "/houdini/exercise/a.hiplc"],
        "file_location_records": {    # only the RECORD stores these; the retired decoration-table keys are not used
            "/tex/img/": {"registered": True},
            "/tex/bokeh/": {"registered": True, "name": "Bokeh files"},
            "/photo/2023/": {"registered": True, "color": "#134d4d"},
            "/models/obj/": {"registered": True},
            "/houdini/exercise/": {"registered": True},
            "/tex/hdr/": {"registered": True},
        },
    }

    def _prefs(self, settings=None, tag_favourites=True):
        return _location_prefs(self, settings or self.REAL_SHAPE,
                               tag_favourites=tag_favourites)

    def test_every_location_is_stored_field_for_field_in_the_files_database(self):
        prefs, library = _location_prefs(self, {"directory": ""})
        for path, record in self.REAL_SHAPE["file_location_records"].items():
            self.assertTrue(locations_mod.set_record(prefs, path, record), path)
        self.assertEqual(sorted(self.REAL_SHAPE["file_folders"]), sorted(prefs.file_folders))
        self.assertEqual({"registered": True, "name": "Bokeh files"},
                         locations_mod.record(prefs, "/tex/bokeh/"),
                         "a location's record was not read back as written")
        with open(os.path.join(library, "files.json"), encoding="utf-8") as handle:
            written = json.load(handle)
        mine = written["locations"][test_support.FIXTURE_USER]
        self.assertEqual(6, len(mine))
        self.assertTrue(all(key.startswith(locations_mod.LOC_PREFIX) for key in mine))
        self.assertEqual(6, len(written["paths"]), "every location has exactly one path row")

    def test_one_users_folders_are_not_anothers_and_nobody_writes_nothing(self):
        prefs, _library = _location_prefs(self, {"directory": ""})
        locations_mod.register(prefs, "/tex/bokeh/")
        self.assertIn("/tex/bokeh/", prefs.file_folders)
        prefs.library_user = "0f0e0d0c0b0a09080706050403020100"
        self.assertEqual([], list(prefs.file_folders),
                         "a second user sees the first user's registered folders")
        prefs.library_user = ""
        self.assertFalse(locations_mod.set_record(prefs, "/nobody/", {"registered": True}))
        prefs.library_user = test_support.FIXTURE_USER
        self.assertEqual(["/tex/bokeh/"], list(prefs.file_folders))

    def test_a_removal_deletes_what_is_keyed_under_the_location(self):
        from amaze.core import notes
        prefs, _library = _location_prefs(self, {"directory": ""})
        locations_mod.register(prefs, "/tex/bokeh/")
        key = locations_mod.file_ident(prefs, "/tex/bokeh/a.exr")
        self.assertTrue(key.startswith(locations_mod.LOC_PREFIX))
        notes.set_note(prefs, notes.note_key("file", key), [{"t": "text", "text": "nice"}])
        locations_mod.set_favourite(prefs, "/tex/bokeh/a.exr", True)
        locations_mod.unregister(prefs, "/tex/bokeh/")
        self.assertTrue(locations_mod.retire_prefix(prefs, "/tex/bokeh/"))
        self.assertFalse(notes.has_note(prefs, notes.note_key("file", key)))
        self.assertEqual([], locations_mod.favourite_paths(prefs))
        self.assertEqual("", locations_mod.location_id(prefs, "/tex/bokeh/"))

class KindRouterTest(unittest.TestCase):
    """`kind_for` decides every per-type behaviour, using the three sections' extension matchers."""

    def test_each_kind_routes_to_its_section_of_origin(self):
        for name, kind in (
                ("a.hip", "hip"), ("b.HIPLC", "hip"), ("c.hipnc", "hip"),
                ("d.png", "image"), ("e.EXR", "image"), ("f.hdr", "image"),
                ("m.rat", "image"),    # Houdini's own texture format - sips fails cleanly on it, the iconvert fallback converts it
                ("n.dng", "image"), ("o.DNG", "image"),    # camera raw macOS decodes natively (probed: sips converts a real DNG in ~2.3s)
                ("g.bgeo.sc", "geometry"), ("h.obj", "geometry"),
                ("i.usd", "geometry"), ("i2.usdz", "geometry"),    # the File SOP reads these ▸r/file-sop-formats
                ("i3.glb", "geometry"), ("i4.gltf", "geometry"), ("i5.dxf", "geometry"),
                ("i6.iges", "geometry"), ("i7.IGS", "geometry"),
                ("p.pic", "image"), ("q.psd", "image"), ("r.gif", "image"), ("s.tx", "image"),
                ("j.txt", "other"), ("k.bvh", "other"), ("noext", "other"),
                ("l.hip.bak", "other"), ("v.vdb", "other")):    # a cache is not rendered unless requested
            self.assertEqual(kind, file_library.kind_for(name), name)

    def test_the_router_agrees_with_the_three_recognisers(self):
        from amaze.core import scene_files, texture_library

        def by_recogniser(name):
            if scene_files.matched_extension(name):
                return "hip"
            if texture_library.matched_extension(name):
                return "image"
            if geo_library.matched_extension(name):
                return "geometry"
            return "other"

        for name in ("A.HIP", "a.Hiplc", "x.BGEO.SC", "x.bgeo.SC", "x.bgeo", "shot.v001.EXR",
                     "name.exr.txt", "hip", ".hip", "png", "a.", "", "a.tx", "a.TX", "a.txt",
                     "É.PNG", "a.usd.bak", "a.hip.png", "a.png.hip", "a b.jpeg"):
            self.assertEqual(by_recogniser(name), file_library.kind_for(name), repr(name))
        with mock.patch.object(scene_files, "HIP_EXTENSIONS", (".Scene", "")):
            self.assertEqual("hip", file_library.kind_for("a.SCENE"), "the case of a HIP_EXTENSIONS entry decided the match")
            self.assertEqual("other", file_library.kind_for("a.dat"), "an empty entry matched every name")

    def test_the_loader_sop_follows_the_file_type(self):
        for name, sop in (("a.abc", "alembic"), ("b.usd", "usdimport"), ("c.USDZ", "usdimport"),
                          ("d.glb", "file"), ("e.fbx", "file"), ("f.dxf", "file")):
            self.assertEqual(sop, geo_library.loader_sop_for(name), name)


class ScenePathsAreSpelledPerPreferenceTest(unittest.TestCase):
    """Every path written into the scene goes through `scene_path`, the Write Paths As preference."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def test_the_geometry_loader_writes_the_spelled_path(self):
        home = self._home()
        geo = hou.node("/obj").createNode("geo", "amaze_pathtest_dest")
        self.addCleanup(geo.destroy)
        self.panel.drop_placement.import_geo_in_context(
            home + "/models/amaze_spelling.obj", geo)
        loaders = [n for n in geo.children() if n.type().name() == "file"]
        self.assertTrue(loaders, "no loader SOP was created")
        self.assertEqual(
            "$HOME/models/amaze_spelling.obj",
            loaders[0].parm("file").rawValue(),
            "the geometry import writes the raw absolute path")

    def test_the_drag_payload_is_the_spelled_text_and_nothing_else(self):
        """The drag holds only the spelled text: Houdini treats a file URL as a file to open."""
        home = self._home()
        raw = home + "/textures/amaze_spelling.png"
        mime = self.panel.thumblist._file_drag_mime(self.panel, raw)
        self.assertEqual("$HOME/textures/amaze_spelling.png",
                         mime.text(),
                         "the drag's text flavour is not spelled per "
                         "the preference")
        self.assertFalse(mime.hasUrls(),
                         "the drag has a file URL again - Houdini "
                         "opens it as a file")


class AGeometryImportMakesItsNodeCurrent(unittest.TestCase):
    """The geometry import leaves its new node current and selected, as the Tab menu does."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_imported_geometry_is_the_current_node(self):
        index = mock.MagicMock()
        index.data.return_value = "/nowhere/amaze_fronted.obj"
        with mock.patch.object(self.panel, "_active_network_pwd",
                               return_value=hou.node("/obj")):
            self.panel.import_geo_asset(index)
        made = hou.node("/obj/amaze_fronted")
        self.assertIsNotNone(made, "premise: the import made no geo node")
        self.addCleanup(made.destroy)
        self.assertTrue(made.isCurrent(),
                        "the imported geometry is not the current node")
        self.assertIn(made, hou.selectedNodes(),
                      "the imported geometry is not selected")


class DropFilePathOnNodeTest(unittest.TestCase):
    """The node's first file parameter gets the spelled path; a node without one returns False."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def _index_for(self, path):
        import types
        return types.SimpleNamespace(data=lambda role: path)

    def test_the_first_file_parm_takes_the_spelled_path_and_no_file_parm_returns_false(self):
        home = self._home()
        geo = hou.node("/obj").createNode("geo", "amaze_droptest")
        self.addCleanup(geo.destroy)
        loader = geo.createNode("file")
        self.assertTrue(self.panel.sections["file"].drop_file_path_on_node(
            self._index_for(home + "/textures/amaze_drop.png"), loader))
        self.assertEqual(
            "$HOME/textures/amaze_drop.png",
            loader.parm("file").rawValue(),
            "drop_file_path_on_node wrote a raw absolute path")
        bare = geo.createNode("null")
        self.assertFalse(
            self.panel.sections["file"].drop_file_path_on_node(
                self._index_for(home + "/x.png"), bare),
            "a node with no file parameter returned True")


class CreationRuleTest(unittest.TestCase):
    """Empty space creates the carrier where the network's child category has the type, else False."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        hou.clearAllSelected()

    def _home(self):
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no HOME variable in this session")
        return home

    def _matnet(self):
        net = hou.node("/obj").createNode("matnet")
        self.addCleanup(net.destroy)
        return net

    def _geo(self):
        net = hou.node("/obj").createNode("geo")
        self.addCleanup(net.destroy)
        return net

    def _index_for(self, path, kind=None):
        import types
        from amaze.core import file_library
        roles = {file_library.FileFiles.PathRole: path}
        if kind is not None:
            roles[file_library.FileFiles.KindRole] = kind
        return types.SimpleNamespace(
            data=lambda role: roles.get(role, path),
            isValid=lambda: True)

    def test_an_image_becomes_a_mtlximage_and_a_sop_network_returns_false(self):
        from amaze.helpers import helpers

        home = self._home()
        net = self._matnet()
        self.assertTrue(self.panel.sections["file"].create_image_node_in(
            self._index_for(home + "/textures/amaze_create.png"), net))
        children = net.children()
        self.assertEqual(1, len(children), "exactly one carrier")
        self.assertIn("mtlximage", children[0].type().name())
        self.assertEqual(
            "$HOME/textures/amaze_create.png",
            helpers.find_file_parm(children[0]).rawValue(),
            "the carrier holds a raw absolute path")
        sop = self._geo()
        self.assertFalse(self.panel.sections["file"].create_image_node_in(
            self._index_for(home + "/x.png"), sop))
        self.assertEqual((), sop.children(),
                         "a network that cannot hold it gained a child anyway")

    def test_a_gradient_becomes_an_mtlx_ramp_node(self):
        from amaze.helpers import helpers

        net = self._matnet()
        index = self.panel.gradient_sorted_model.index(0, 0)
        self.assertTrue(index.isValid(),
                        "premise: the fixture has gradients")
        self.assertTrue(self.panel.sections["gradient"].create_gradient_node_in(index, net))
        children = net.children()
        self.assertEqual(1, len(children))
        self.assertIn("hmtlxrampc", children[0].type().name())
        self.assertIsNotNone(
            helpers.find_color_ramp_parm(children[0]),
            "the carrier has no ramp parameter for the gradient")

    def test_a_vex_snippet_becomes_a_wrangle_in_sops_and_vops_return_false(self):
        from amaze.helpers import helpers

        net = self._geo()
        index = self.panel.code_sorted_model.index(0, 0)
        self.assertTrue(index.isValid(),
                        "premise: the fixture has snippets")
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.assertTrue(self.panel.sections["code"].create_code_node_in(index, net))
        children = net.children()
        self.assertEqual(1, len(children))
        self.assertIn("attribwrangle", children[0].type().name())
        self.assertEqual(
            asset.code, helpers.find_code_parm(children[0]).eval(),
            "the wrangle does not contain the snippet")
        vop = self._matnet()
        self.assertFalse(self.panel.sections["code"].create_code_node_in(index, vop),
                         "a VOP network took a VEX snippet")
        self.assertEqual((), vop.children())

    def _with_view_networks(self, networks):
        self.panel._view_create_networks = lambda: list(networks)
        self.addCleanup(
            lambda: self.panel.__dict__.pop("_view_create_networks", None))

    def test_a_node_created_at_a_position_is_never_auto_placed(self):
        """A given position is the placement; moveToGoodPosition runs only as the no-position fallback."""
        from unittest import mock
        net = self._matnet()
        spot = hou.Vector2(-3.5, -2.25)
        with mock.patch.object(hou.Node, "moveToGoodPosition") as auto:
            ok = self.panel.sections["file"].create_image_node_in(
                self._index_for(self._home() + "/x.png"), net,
                position=spot)
        self.assertTrue(ok)
        auto.assert_not_called()
        child = net.children()[0]
        from amaze.helpers import helpers
        anchor = helpers.centred_on(spot)
        self.assertEqual((anchor.x(), anchor.y()),
                         (child.position().x(), child.position().y()),
                         "the carrier is not centred on the release "
                         "point")

    def test_the_release_position_stays_in_its_own_space(self):
        """Over a container, the position resolves only when the editor under the cursor shows it."""
        from unittest import mock
        import types
        inside = self._matnet()
        outer = self._geo()
        editor = types.SimpleNamespace(
            type=lambda: hou.paneTabType.NetworkEditor,
            pwd=lambda: outer,
            cursorPosition=lambda: hou.Vector2(9.0, 9.0))
        from amaze.core import dragengine
        with mock.patch.object(dragengine, "pane_tab_under_cursor",
                               return_value=editor):
            self.assertIsNone(
                self.panel.drop_placement.release_position_in(inside),
                "an editor showing another network gave its coordinates to the "
                "destination network")
            got = self.panel.drop_placement.release_position_in(outer)
        self.assertEqual((9.0, 9.0), (got.x(), got.y()))

    def test_a_creation_restores_the_prior_selection(self):
        """Houdini selects new nodes and makes them current; a creation restores the prior selection."""
        sop = self._geo()
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        hou.clearAllSelected()
        self.panel.click_on_row(self.panel.sections["code"], index)
        self.assertEqual(1, len(sop.children()), "premise: created")
        self.assertEqual(
            (), hou.selectedNodes(),
            "the new carrier stayed selected - the next double-click "
            "would apply to it")

    def test_a_menu_copy_to_selects_the_imported_material(self):
        """Copy To imports into /mat and leaves the new material selected, as the Tab menu does."""
        net = self._geo()
        self._with_view_networks([net])
        keeper = net.createNode("box", "the_artists_own")
        keeper.setSelected(True, clear_all_selected=True)
        proxy = self.panel.material_sorted_model
        index = None
        for row in range(proxy.rowCount()):
            candidate = proxy.index(row, 0)
            source = proxy.mapToSource(candidate)
            asset = self.panel.material_model.assets[source.row()]
            if str(getattr(asset, "renderer", "")):
                index = candidate
                break
        if index is None:
            self.skipTest("no fixture material has a renderer")
        self.panel.material_selection_model.select(
            index,
            QtCore.QItemSelectionModel.ClearAndSelect
            | QtCore.QItemSelectionModel.Rows)
        mat_net = hou.node("/mat")
        held = set(mat_net.children())
        self.panel.sections["material"].menu_copy_to(
            (index,), index, payload="mat")
        new = [n for n in mat_net.children() if n not in held]
        if not new:
            self.skipTest("the fixture material did not import")
        self.assertIn(new[0], hou.selectedNodes(),
                      "a menu Copy To did not leave the imported material selected")
        self.assertTrue(new[0].isCurrent(),
                        "the imported material is not the current node")

    def test_the_click_dispatcher_catches_permission_error_and_raises_other_errors(self):
        """A locked network's PermissionError is caught as on a drop; any other error still raises."""
        from amaze.panel import sections as sections_module

        class PermissionErrorSection:
            key = "refusing"
            DROP = sections_module.DropRule(
                click_resolve="refuse_for_the_test")

            def refuse_for_the_test(self, _index):
                raise hou.PermissionError(
                    "Cannot create a node inside a locked asset")

        class CrashingSection:
            key = "crashing"
            DROP = sections_module.DropRule(
                click_resolve="crash_for_the_test")

            def crash_for_the_test(self, _index):
                raise RuntimeError("a real defect")

        index = self.panel.code_sorted_model.index(0, 0)
        self.panel.click_on_row(PermissionErrorSection(), index)
        with self.assertRaises(RuntimeError):
            self.panel.click_on_row(CrashingSection(), index)

    def test_the_drag_preview_names_the_node_the_drop_creates(self):
        """The drag preview names the node a drop on empty space creates, from the same DropRule."""
        from amaze.panel import dragdrop_widgets, sections as sections_mod
        sop = self._geo()
        vop = self._matnet()
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        rule = sections_mod.SECTION_INDEX["code"].DROP
        promised = dragdrop_widgets.GridGestureMixin._preview_node_type(    # the index is passed in, as the live drag passes it
            self.panel, rule, "code", sop, index)
        self.assertTrue(self.panel.sections["code"].create_code_node_in(index, sop))
        made = [c for c in sop.children() if "wrangle" in c.type().name()]
        self.assertEqual(promised, made[0].type().name(),
                         "the drag preview showed a different node than the "
                         "drop created")
        self.assertEqual(
            "", dragdrop_widgets.GridGestureMixin._preview_node_type(
                self.panel, rule, "code", vop),
            "a network with no carrier still got a preview node type")

    def test_dragengine_end_clears_every_overlay(self):
        """The overlay is one slot per editor; dragengine.end() clears it on release, cancel and leave."""
        from amaze.core import dragengine
        cleared = []

        class _Editor:
            def setOverlayShapes(self, shapes):
                if not shapes:
                    cleared.append(True)

        editor = _Editor()
        dragengine._editors_with_overlay.append(editor)
        dragengine.end()
        self.assertTrue(cleared, "the overlay was never cleared")
        self.assertEqual([], dragengine._editors_with_overlay,
                         "`dragengine._editors_with_overlay` still lists an editor")

    def test_the_editor_is_restored_to_its_own_network(self):
        """An import moves an unpinned editor elsewhere, so its PWD is saved and restored."""
        from unittest import mock
        import types
        from amaze.helpers import helpers
        home = self._geo()
        away = hou.node("/mat")
        anchor = home.createNode("box")
        seen = []

        class _Tab:
            def type(self):
                return hou.paneTabType.NetworkEditor

            def pwd(self):
                return self._pwd

            def setPwd(self, node):
                self._pwd = node
                seen.append(("pwd", node.path()))

            def currentNode(self):
                return anchor

            def setCurrentNode(self, node):
                seen.append(("current", node.path()))

        tab = _Tab()
        tab._pwd = home
        ui = types.SimpleNamespace(paneTabs=lambda: [tab])
        with mock.patch.object(hou, "ui", ui, create=True):
            with helpers.preserving_selection_and_current():
                tab._pwd = away          # the network change an import causes
        self.assertEqual(home, tab.pwd(),
                         "the editor was left in the network the "
                         "import moved it into")
        self.assertIn(("pwd", home.path()), seen)

    def test_the_selection_is_restored_with_no_undo_steps(self):
        """Selection calls push undo entries, so the restore runs under hou.undos.disabler()."""
        from unittest import mock
        from amaze.helpers import helpers
        net = self._geo()
        a = net.createNode("box")
        b = net.createNode("sphere")
        hou.clearAllSelected()
        a.setSelected(True)
        real = hou.undos.disabler
        used = []

        def _watch():
            used.append(True)
            return real()

        with mock.patch.object(hou.undos, "disabler", _watch):
            with helpers.preserving_selection_and_current():
                a.setSelected(False)
                b.setSelected(True)
        self.assertTrue(used, "the restore ran outside a disabler - "
                              "every drop now adds undo steps")
        self.assertEqual((a,), hou.selectedNodes(),
                         "the block did not put the selection back")

    def _editor_showing(self, home, anchor, seen):
        """A fake network editor at `home` with `anchor` current, so a put-back calls setCurrentNode."""
        import types

        class _Tab:
            _pwd = home

            def type(self):
                return hou.paneTabType.NetworkEditor

            def pwd(self):
                return self._pwd

            def setPwd(self, node):
                self._pwd = node
                seen.append(("pwd", node.path()))

            def currentNode(self):
                return anchor

            def setCurrentNode(self, node):
                seen.append(("current", node.path()))

        return types.SimpleNamespace(paneTabs=lambda: [_Tab()])

    def test_the_deferred_restore_waits_while_amaze_is_still_busy(self):
        """A save's deferred pass must not run inside processEvents. ▸r/editor-put-back"""
        from amaze.helpers import helpers
        home = self._geo()
        anchor = home.createNode("box")
        seen = []
        with mock.patch.object(hou, "ui", self._editor_showing(home, anchor, seen),
                               create=True):
            with helpers.preserving_selection_and_current():    # the save's own block schedules the deferred pass
                pass
            seen.clear()

            def pump():
                QtWidgets.QApplication.processEvents()    # Houdini's Esc check inside createNode
                self.assertEqual([], seen, "the put-back ran during Amaze's own call")

            test_support.call_as_amaze(pump)
            test_support.settle(lambda: any(s[0] == "current" for s in seen))
        self.assertEqual([("current", anchor.path())],
                         [s for s in seen if s[0] == "current"],
                         "the put-back did not run once the event loop was idle")

    def test_a_nested_block_schedules_no_restore_of_its_own(self):
        """An inner block's deferred pass would run last and restore a mid-operation state."""
        from amaze.helpers import helpers
        home = self._geo()
        anchor = home.createNode("box")
        seen, passes = [], []
        real = helpers._restore_editors

        def _watch(editors, pass_name):
            passes.append(pass_name)
            return real(editors, pass_name)

        with mock.patch.object(hou, "ui", self._editor_showing(home, anchor, seen),
                               create=True), \
                mock.patch.object(helpers, "_restore_editors", _watch):
            with helpers.preserving_selection_and_current():
                with helpers.preserving_selection_and_current():
                    pass
                QtWidgets.QApplication.processEvents()
                self.assertEqual(["immediate"], passes,
                                 "a nested block scheduled or ran a pass of its own")
            test_support.settle(lambda: "deferred" in passes)
        self.assertEqual(["immediate", "immediate", "deferred"], passes)

    def test_the_click_and_the_menu_treat_a_selected_node_alike(self):
        """A selected node that cannot take the snippet falls through to creation; one that can gets it."""
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        section = self.panel.sections["code"]
        for route, selected, children in (("click", "sphere", 2),
                                          ("menu", "sphere", 2),
                                          ("menu", "attribwrangle", 1)):
            with self.subTest(route=route, selected=selected):
                sop = self._geo()
                node = sop.createNode(selected)
                hou.clearAllSelected()
                node.setSelected(True)
                self._with_view_networks([sop])
                if route == "click":
                    self.panel.click_on_row(section, index)
                else:
                    section.menu_apply([index], index)    # the handler the menu table names
                wrangles = [c for c in sop.children()
                            if "wrangle" in c.type().name()]
                self.assertEqual(
                    (children, 1), (len(sop.children()), len(wrangles)),
                    "the %s path with a %s selected blocked the creation, or "
                    "created beside a node that could take it"
                    % (route, selected))

    def test_a_locked_asset_is_skipped_and_the_editable_subnet_gets_the_node(self):
        """The walk skips a locked HDA's levels to its editable `create` subnet and unlocks nothing."""
        stage = hou.node("/stage")
        sc = stage.createNode("sopcreate")
        self.addCleanup(sc.destroy)
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        section = self.panel.sections["code"]
        editable = sc.node("sopnet/create")
        self.assertTrue(editable.isEditableInsideLockedHDA(),
                        "premise: the create subnet is marked editable")
        self._with_view_networks([sc, sc.node("sopnet"), editable])    # locked levels first - the walk sees all three, only the last can take the carrier
        hou.clearAllSelected()
        before = len(editable.children())
        self.panel.click_on_row(section, index)
        self.assertEqual(before + 1, len(editable.children()),
                         "the walk did not reach the editable subnet")
        self.assertTrue(sc.isLockedHDA(),
                        "the asset was UNLOCKED to create the node")

    def test_a_geo_double_click_fills_the_selected_node(self):
        """A double-click tries the selection first: a node with a file parameter takes the path."""
        import types
        from amaze.core import file_library
        from amaze.helpers import helpers
        sop = self._geo()
        loader = sop.createNode("file")
        hou.clearAllSelected()
        loader.setSelected(True)
        self._with_view_networks([sop])
        path = self._home() + "/models/amaze_click.obj"
        roles = {file_library.FileFiles.KindRole: locations_mod.KIND_GEO,
                 file_library.FileFiles.PathRole: path}
        index = types.SimpleNamespace(
            data=lambda role: roles.get(role, path),
            isValid=lambda: True)
        self.panel.click_on_row(self.panel.sections["file"], index)
        self.assertEqual(
            "$HOME/models/amaze_click.obj",
            helpers.find_file_parm(loader).rawValue(),
            "the selected file node did not take the spelled path")
        self.assertEqual(
            1, len(sop.children()),
            "the double-click imported beside the selection instead of "
            "filling it")

    def test_click_on_row_ignores_a_selection_outside_the_visible_editors(self):
        """A double-click considers only selected nodes inside the visible editors' networks."""
        sop = self._geo()
        elsewhere = self._matnet()
        stray = elsewhere.createNode("mtlxstandard_surface")
        stray.setSelected(True)
        self._with_view_networks([sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.panel.click_on_row(self.panel.sections["code"], index)
        self.assertEqual(
            1, len(sop.children()),
            "a selected node in no visible network took the double-click")

    def test_double_click_with_nothing_selected_creates_a_new_node(self):
        from amaze.helpers import helpers

        home = self._home()
        net = self._matnet()
        self._with_view_networks([net])
        self.panel.click_on_row(
            self.panel.sections["file"],
            self._index_for(home + "/textures/amaze_dbl.png",
                            kind=locations_mod.KIND_IMAGE))
        children = net.children()
        self.assertEqual(1, len(children),
                         "the empty-selection double-click did not "
                         "create the carrier")
        self.assertEqual(
            "$HOME/textures/amaze_dbl.png",
            helpers.find_file_parm(children[0]).rawValue())

    def test_click_on_row_finds_the_network_that_supports_the_payload(self):
        """One resolver walks the visible networks; the first that can hold the carrier is used."""
        vop = self._matnet()
        sop = self._geo()
        self._with_view_networks([vop, sop])
        index = self.panel.code_sorted_model.index(0, 0)
        source = self.panel.code_sorted_model.mapToSource(index)
        asset = self.panel.code_model.assets[source.row()]
        if str(getattr(asset, "renderer", "")).lower() != "vex":
            self.skipTest("the first snippet is not VEX")
        self.panel.click_on_row(self.panel.sections["code"], index)
        self.assertEqual((), vop.children(),
                         "the network that cannot hold it gained the carrier")
        children = sop.children()
        self.assertEqual(1, len(children),
                         "the supporting network never got the "
                         "carrier - the double-click stopped at the first "
                         "unsupported network")
        self.assertIn("attribwrangle", children[0].type().name())


class HoudiniPathTest(unittest.TestCase):
    """Copy Path writes paths the way Houdini writes them."""

    def test_a_home_path_collapses_by_default_and_others_stay_absolute(self):
        """The default is $HOME: a path under $HIP is written $HOME/... unless set otherwise."""
        self.assertEqual(
            "/mnt/somewhere/else.txt",
            helpers.houdini_path("/mnt/somewhere/else.txt"))
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        self.assertEqual(
            "$HOME/textures/wood.png",
            helpers.houdini_path(home + "/textures/wood.png"))
        self.assertEqual(
            home + "/x.png",
            helpers.houdini_path(home + "/x.png", "absolute"),
            "the absolute style collapsed")
        self.addCleanup(hou.putenv, "HIP", hou.text.expandString("$HIP"))
        hou.putenv("HIP", home + "/amaze_hip")    # its own $HIP: hython's is wherever the suite started
        collapsed = helpers.houdini_path(home + "/amaze_hip/render.exr")
        self.assertTrue(collapsed.startswith("$HOME/"),
                        "the default style is not $HOME: %r" % collapsed)

    def test_default_restores_the_cache_path(self):
        """Default on the Cache Path row clears the preference, so the machine default applies."""
        from amaze.dialogs import prefs_window
        from amaze.helpers import hostos as hostos_mod

        p = test_support.fixture_prefs(self)
        p.cache_dir = "/somewhere/else"
        state = prefs_window.AmazePrefsState(p, panel=None)

        state.resetCachePath()
        self.assertEqual(hostos_mod.cache_root(), state.cachePath,
                         "the field still shows the old path")
        state.apply()

        self.assertEqual("", p.cache_dir,
                         "a literal path was written instead of the "
                         "preference being cleared")

    @staticmethod
    def _shown_user(state):
        """The name the User row shows for the user picked."""
        from amaze.dialogs import prefs_window
        picked = state.getPref(prefs_window.USER)
        return next((row["text"] for row in state.userOptions if row["value"] == picked), "")

    def test_the_user_field_shows_a_real_name(self):
        """The User row shows names, never UIDs, and creates no user before Apply."""
        from amaze.core import users
        from amaze.dialogs import prefs_window
        p = test_support.fixture_prefs(self)
        p.library_user = ""
        state = prefs_window.AmazePrefsState(p, panel=None)
        self.assertEqual("", state.getPref(prefs_window.USER),
                         "a user was selected in a library that has no users")
        self.assertEqual({}, users.all_users(p), "opening Preferences created a user")
        state.create_user("  MyOwnName  ")
        self.assertEqual("MyOwnName", self._shown_user(state))
        self.assertEqual({}, users.all_users(p), "a user was made before Apply")
        state.apply()
        self.assertEqual(0, state.changeCount, "Apply left the new user pending")
        uid = p.library_user
        self.assertEqual({uid: "MyOwnName"}, users.all_users(p),
                         "Apply did not make the user it showed")
        self.assertNotEqual("MyOwnName", uid,
                            "`library_user` holds the NAME, not a UID")
        state.rename_user("Renamed")
        self.assertEqual("Renamed", users.name_for(p, uid),
                         "after the rename the UID does not map to the new name")
        self.assertEqual(uid, p.library_user,
                         "a RENAME created a new UID")
        self.assertEqual("Renamed", self._shown_user(state),
                         "the dropdown still shows the old name")

    def test_the_user_row_switches_between_the_librarys_users_on_apply(self):
        """The User row lists the library's users; a pick switches this computer on Apply."""
        from amaze.core import users
        from amaze.dialogs import prefs_window
        p = test_support.fixture_prefs(self)
        first = users.create(p, "Cobalt")
        second = users.create(p, "Sienna")
        p.library_user = first
        state = prefs_window.AmazePrefsState(p, panel=None)
        listed = {row["text"] for row in state.userOptions}
        self.assertIn("Cobalt", listed)
        self.assertIn("Sienna", listed)
        self.assertEqual("Cobalt", self._shown_user(state),
                         "the dropdown opened on another user")
        state.setPref(prefs_window.USER, second)    # what the User row's menu sends
        self.assertEqual(first, p.library_user,
                         "picking a user switched this computer before Apply")
        state.apply()
        self.assertEqual(second, p.library_user,
                         "Apply did not switch this computer to the picked user")

    def test_the_pref_validates_and_defaults_home(self):
        from amaze.prefs import prefs as prefs_module
        p = prefs_module.Prefs()
        self.assertEqual("home", p.path_style)
        p.path_style = "job"
        self.assertEqual("job", p.path_style)
        p.path_style = "nonsense"
        self.assertEqual("home", p.path_style,
                         "an invalid token was accepted")


class _Prefs:
    """Only what FileFiles reads, over the real location store; derived tables are not cached."""

    def __init__(self, folders=()):
        self.dir = tempfile.mkdtemp(prefix="amaze_file_lib_")
        self.library_user = test_support.FIXTURE_USER    # a user-tagged store with no user would reject every register call
        self.path_style = "home"
        self.last_file_folder = ""
        self.rendersize = 256
        self.icon_line_weight = "template"
        self.texture_parallel_conversions = 1
        self.geometry_shading_mode = "hiddenlineghost"
        self.geometry_bg = "black"
        self.render_rat_files = True    # the tests here that convert a .rat predate the switch
        self.system_file_icons = True
        self._records: dict = {}
        self._order: list = []
        self._favourites: list = []
        for path in folders:
            self.add_file_folder(path)

    @property
    def last_known_folders(self):
        return self._order

    @property
    def last_known_favourites(self):
        return self._favourites

    @property
    def last_known_records(self):
        return self._records

    def keep_last_known(self, records, order, favourites):
        if records is not None:
            self._records = {k: dict(v) for k, v in records.items()}
        if order is not None:
            self._order = list(order)
        if favourites is not None:
            self._favourites = list(favourites)

    def save(self):
        pass

    @property
    def file_folders(self):
        return locations_mod.registered_paths(self)

    @property
    def file_favorites(self):
        return locations_mod.favourite_paths(self)

    @property
    def file_folder_names(self):
        return self._table("name")

    @property
    def file_folder_colors(self):
        return self._table("color")

    def _table(self, field):
        table = {}
        for path in locations_mod.paths(self):
            record = locations_mod.record(self, path)
            if field in record:
                table[path] = record[field]
        return table

    def add_file_folder(self, path):
        locations_mod.register(self, path)

    def remove_file_folder(self, path):
        locations_mod.unregister(self, path)

    def relocate_file_folder(self, old, new):
        if not locations_mod.record(self, old):
            return False
        return bool(locations_mod.relocate_record(self, old, new))    # the same body as the product's method

    def add_file_favorite(self, path):
        locations_mod.set_favourite(self, path, True)

    def remove_file_favorite(self, path):
        locations_mod.set_favourite(self, path, False)

    def set_file_folder_name(self, path, name):
        locations_mod.set_field(self, path, "name", str(name or "").strip())

    def set_file_folder_color(self, path, color):
        locations_mod.set_field(self, path, "color", str(color or "").strip())


class FileKeyIsCanonicalTest(unittest.TestCase):
    """`file_key` is one spelling per file however its location is spelled, `..` included."""

    def _model_over(self, folder):
        from amaze.helpers import hostos  # noqa: F401 - guard below
        model = file_library.FileFiles(_Prefs([folder]))
        model.set_folder(folder)
        return model

    def test_the_key_is_one_spelling_however_the_location_is_spelled(self):
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.mkdir(os.path.join(tmp, "sub"))
        with open(os.path.join(tmp, "a.png"), "w") as handle:
            handle.write("x")
        detour = os.path.join(tmp, "sub", os.pardir)
        model = self._model_over(detour)
        self.assertGreater(model.rowCount(), 0, "the fixture scanned "
                                                "nothing - this test is "
                                                "not testing keys")
        straight = file_library.FileFiles(model.preferences)
        straight.set_folder(tmp)
        keys = [model.file_key(r) for r in range(model.rowCount())]
        self.assertEqual(
            keys,
            [straight.file_key(r) for r in range(straight.rowCount())],
            "the same file reached through a differently-spelled "
            "location gets a different key, and its comment and "
            "icon are keyed to the spelling")
        for key in keys:
            self.assertTrue(
                key.startswith("loc:"),
                "file_key %r is not the location-keyed ident - keyed "
                "by path, its data is lost when the folder moves" % key)
        self.assertEqual("", model.file_key(999))    # normpath("") is ".", truthy past every `if not key`
        self.assertEqual("", model.file_key(-1))

    def test_a_capture_taken_by_path_shows_on_the_tile(self):
        """The shelf names a scene by its path, the menu by its row: both find one capture file."""
        from amaze.core import captures
        tmp = tempfile.mkdtemp(prefix="amaze_key_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        scene = os.path.join(tmp, "shot.hiplc")
        with open(scene, "w") as handle:
            handle.write("x")
        model = self._model_over(tmp)
        row = model.row_for_path(scene)
        self.assertGreaterEqual(row, 0, "the scene is not listed")
        key = captures.file_key(model.preferences, scene)
        self.assertTrue(key.startswith("loc:"), "the capture is keyed by path: %r" % key)
        self.assertEqual(model.tile_key(row), key)
        self.assertEqual(model.capture_path(row), captures.file_path(model.preferences, key))


class OsIconTest(unittest.TestCase):
    """An unrecognised file gets the OS icon on a tile-sized canvas, never scaled past 2x."""

    def _model_with(self, *names):
        tmp = tempfile.mkdtemp(prefix="amaze_osicon_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in names:
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        model = file_library.FileFiles(_Prefs([tmp]))
        files_actions.connect(model, file_library.FileFolders(model.preferences),
                              os_icon=delegates.os_file_icon)    # as the panel does
        model.set_folder(tmp)
        return model

    def test_an_unknown_file_shows_the_system_icon_until_generic_is_chosen(self):
        """Render is the default for a file Amaze makes no preview of: the system icon; Generic is T11."""
        for name in ("mocap.bvh", "README"):
            with self.subTest(name=name):
                model = self._model_with(name)
                shown = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.DecorationRole)
                self.assertIsNotNone(shown)
                self.assertFalse(shown.isNull(), "the default icon is empty")
                self.assertEqual(1, len(model._os_icons),
                                 "the default did not request the system icon")
                with mock.patch.object(model, "tile_icon", return_value={"face": "generic"}):
                    face = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.DecorationRole)
                self.assertEqual(tile_icons.generic_image("face_file"), face)
                if name == "README":    # no extension: the generic system icon, never blank
                    continue
                self.assertNotEqual(face, shown, "the default shows the file face")

    def test_with_system_file_icons_off_every_such_file_shows_the_generic_icon(self):
        own = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
        own.fill(QtGui.QColor("#336699"))
        model = self._model_with("mocap.bvh")
        model.os_icon = lambda _path, _side: own
        model.preferences.system_file_icons = False
        shown = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertEqual(tile_icons.generic_image("face_file"), shown)

    def test_one_icon_is_composed_per_extension_not_per_file(self):
        model = self._model_with("a.log", "b.log", "c.log")
        with mock.patch.object(model, "tile_icon", return_value={"face": "image"}):
            for row in range(3):
                model.data(model.index(row, 0),
                           QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertEqual(1, len(model._os_icons),
                         "a folder of logs composed three identical "
                         "icons instead of one")


class AFailedConversionShowsTheFileFaceTest(unittest.TestCase):
    """An image no converter reads shows the generic file face once it fails, not a blank card."""

    def test_the_card_turns_generic_once_the_engine_marks_it_missing(self):
        from amaze.core import conversion, thumbnails
        tmp = tempfile.mkdtemp(prefix="amaze_failed_convert_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "broken.png"), "w") as handle:
            handle.write("not a picture")
        model = file_library.FileFiles(_Prefs([tmp]))
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", ()):    # no converter to fall back on
            model.set_folder(tmp)
            key, source, _payload = model._row_specs[0]
            self.addCleanup(thumbnails.engine.discard, key)
            self.assertEqual("convert", source, "premise: the image was not queued to convert")
            deadline = time.monotonic() + 10
            while not thumbnails.engine.is_missing(key) and time.monotonic() < deadline:
                QtWidgets.QApplication.processEvents()
        self.assertTrue(thumbnails.engine.is_missing(key), "premise: the conversion never failed")
        face = model.data(model.index(0, 0), QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertEqual(tile_icons.generic_image("face_file"), face,
                         "a failed conversion left a blank card")


class ARatFileShowsItsFaceUnlessRenderedTest(unittest.TestCase):
    """A `.rat` file shows the rat face and is not converted; Render RAT Files turns rendering on."""

    def _model(self, render):
        """A folder holding floor.rat and plate.png: (model, {name: row}, names asked to convert)."""
        from amaze.core import thumbnails
        tmp = tempfile.mkdtemp(prefix="amaze_rat_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("floor.rat", "plate.png"):
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("not a picture")
        prefs = _Prefs([tmp])
        prefs.render_rat_files = render
        model = file_library.FileFiles(prefs)
        with mock.patch.object(thumbnails.engine, "request_convert") as asked:
            model.set_folder(tmp)
        rows = {model._files[row][1]: row for row in range(len(model._files))}
        return model, rows, sorted(os.path.basename(call.args[1]) for call in asked.call_args_list)

    def test_with_the_switch_off_a_rat_file_is_not_converted_and_shows_the_rat_face(self):
        model, rows, asked = self._model(render=False)
        self.assertEqual(["plate.png"], asked)
        face = model.data(model.index(rows["floor.rat"], 0), QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertEqual(tile_icons.generic_image("face_rat"), face)
        self.assertNotEqual(tile_icons.generic_image("face_file"), face,
                            "the rat face is the file face")
        self.assertEqual(locations_mod.KIND_IMAGE, model._kinds[rows["floor.rat"]],
                         "a .rat file no longer loads as an image")

    def test_with_the_switch_on_a_rat_file_is_converted_like_any_image(self):
        _model, _rows, asked = self._model(render=True)
        self.assertEqual(["floor.rat", "plate.png"], asked)

    def test_render_image_leaves_a_rat_file_alone_while_the_switch_is_off(self):
        from amaze.core import thumbnails
        model, rows, _asked = self._model(render=False)
        with mock.patch.object(thumbnails.engine, "request_convert") as asked:
            model.rerender_thumbnails([rows["floor.rat"]])
        asked.assert_not_called()
        self.assertFalse(model.renders_thumbnail(rows["floor.rat"]))
        self.assertTrue(model.renders_thumbnail(rows["plate.png"]))

    def test_the_switch_is_off_until_turned_on_and_is_kept_per_user(self):
        from amaze.prefs import persistence
        self.assertIs(False, prefs_module.Prefs().render_rat_files)
        self.assertEqual(("render_rat_files", "_render_rat_files", False),
                         persistence.USER_KEYS["render_rat_files"])


class TheCachePngIsWrittenOffTheGuiThreadTest(unittest.TestCase):
    """A converted image's cache PNG is encoded by the convert worker; the GUI thread only lists it."""

    def test_the_worker_writes_the_png_and_the_manifest_files_it(self):
        from amaze.core import thumbnails
        tmp = tempfile.mkdtemp(prefix="amaze_cache_png_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        picture = QtGui.QImage(320, 200, QtGui.QImage.Format.Format_RGB32)
        picture.fill(QtGui.QColor("#a03020"))
        painter = QtGui.QPainter(picture)
        painter.fillRect(40, 30, 120, 90, QtGui.QColor("#2050c0"))
        painter.end()
        self.assertTrue(picture.save(os.path.join(tmp, "photo.png"), "PNG"))
        model = file_library.FileFiles(_Prefs([tmp]))
        saves, real_save = [], QtGui.QImage.save

        def recording(image, *args, **kwargs):
            on_gui = threading.current_thread() is threading.main_thread()
            saves.append((str(args[0]) if args else "", on_gui))
            return real_save(image, *args, **kwargs)

        with mock.patch.object(QtGui.QImage, "save", recording):
            model.set_folder(tmp)
            key, source, full = model._row_specs[0]
            self.addCleanup(thumbnails.engine.discard, key)
            self.assertEqual("convert", source, "premise: the image was not queued to convert")
            deadline = time.monotonic() + 10
            while model._progress_done < model._progress_total and time.monotonic() < deadline:
                QtWidgets.QApplication.processEvents()
        cache = model._image_cache
        written = [on_gui for path, on_gui in saves if os.path.dirname(path) == cache.cache_dir]
        self.assertTrue(written, "premise: no cache PNG was written")
        self.assertNotIn(True, written, "the cache PNG was encoded on the GUI thread")
        self.assertEqual(cache.png_path(full), cache.valid_path(full),
                         "the written PNG was not recorded in the manifest")


class _RecordingPanel:
    """A fake panel `self` for `click_on_row`: the real dispatch runs, the panel methods record."""

    file_files_model = file_library.FileFiles

    def __init__(self):
        self.calls = []
        self.prefs = _Prefs([])

    def _visible_selected_nodes(self):
        """Nothing selected - this test checks the per-kind dispatch, not the selection path."""
        return []

    def _view_create_networks(self):
        """One writable network, so the empty-space rule can run."""
        return [object()]

    def _cannot_load_here(self):
        self.calls.append("refused")

    def import_geo_asset(self, index):
        self.calls.append("import_geo_asset")

    def copy_file_paths(self, indexes):
        self.calls.append("copy_file_paths")


class _FakeIndex:
    def __init__(self, kind, path="/x/y.ext"):
        self._kind = kind
        self._path = path

    def isValid(self):
        return True

    def data(self, role):
        if role == file_library.FileFiles.KindRole:
            return self._kind
        if role == file_library.FileFiles.PathRole:
            return self._path
        return None


class DoubleClickDispatchTest(unittest.TestCase):
    """Each kind gets its own `DROP_BY_KIND` handler via `click_on_row` on a real FileSection."""

    def test_every_kind_reaches_its_own_handler(self):
        from amaze.panel import panel as panel_mod
        from amaze.panel import sections
        for kind, expected in (("image", "create_image_node_in"),
                               ("geometry", "import_geo_asset"),
                               ("hip", "open_hip_scene"),
                               ("other", "copy_file_paths"),
                               ("", "copy_file_paths")):
            recorder = _RecordingPanel()
            recorder._apply_click_rule = (
                panel_mod.AmazePanel._apply_click_rule.__get__(recorder))
            section = sections.FileSection(recorder)
            section.create_image_node_in = (
                lambda index, network, position=None:
                recorder.calls.append("create_image_node_in") or True)
            section.open_hip_scene = (
                lambda index: recorder.calls.append("open_hip_scene"))
            panel_mod.AmazePanel.click_on_row(
                recorder, section, _FakeIndex(kind))
            self.assertEqual([expected], recorder.calls,
                             "kind %r dispatched %r" % (kind,
                                                        recorder.calls))


class CopyPathTest(unittest.TestCase):
    """Copy Path fills the clipboard with HOUDINI paths, one per line, and no dialog."""

    def test_paths_are_copied_houdini_spelled_one_per_line(self):
        from amaze.panel import drop_placement
        from amaze.panel import panel as panel_mod
        home = hou.expandString("$HOME").replace("\\", "/").rstrip("/")
        if not home or home in ("/", "."):
            self.skipTest("no $HOME in this session")
        recorder = _RecordingPanel()
        recorder.drop_placement = drop_placement.DropPlacement(recorder)    # the real path-spelling code, bound to the stub
        panel_mod.AmazePanel.copy_file_paths(recorder, [
            _FakeIndex("other", home + "/mocap/walk.bvh"),
            _FakeIndex("image", "/mnt/elsewhere/tex.png"),
        ])
        text = QtWidgets.QApplication.clipboard().text()
        self.assertEqual(
            "$HOME/mocap/walk.bvh\n/mnt/elsewhere/tex.png", text,
            "the clipboard does not hold Houdini-style paths, one "
            "per line")


class HipDragLoadsNothingTest(unittest.TestCase):
    """A hip dragged out of Amaze and released loads nothing; a double-click opens the scene."""

    def _hip_harness(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_drag_gesture as harness_mod
        h = harness_mod._Harness(self, "file", kind="hip")
        h.section.open_hip_scene = (
            lambda idx: h.panel.calls.append("open"))
        h.press()
        h.view._dragging = True
        h.view._drag_panel = h.panel
        return h

    def _release_at_global(self, h, global_point):
        """A built QMouseEvent defaults globalPosition() to the real cursor, so the test sets it."""
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(10, 10),
            QtCore.QPointF(global_point),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        h.view.mouseReleaseEvent(event)

    def test_released_outside_or_inside_the_panel_loads_nothing(self):
        h = self._hip_harness()
        self._release_at_global(h, QtCore.QPoint(5000, 5000))
        self.assertNotIn("open", h.panel.calls,
                         "a hip dragged out of Amaze loaded the scene")
        h = self._hip_harness()
        inside = h.panel.mapToGlobal(QtCore.QPoint(5, 5))
        self._release_at_global(h, inside)
        self.assertNotIn("open", h.panel.calls,
                         "a drag that never left the panel loaded the "
                         "scene anyway")


class TooltipWidthTest(unittest.TestCase):
    """Tooltips cap at 800 real screen pixels and wrap; a logical cap doubles on a Retina screen."""

    def _with_dpr(self, dpr):
        """Fix the screen ratio the cap divides by, restored after."""
        from amaze.helpers import theme
        original = theme.screen_ratio
        theme.screen_ratio = lambda widget=None: dpr
        self.addCleanup(setattr, theme, "screen_ratio", original)

    def test_plain_short_text_and_arithmetic_pass_through_untouched(self):
        """Escaping everything would turn `5 < 6` into `5 &lt; 6` on screen; Qt reads it as plain."""
        from amaze.helpers import ui_helpers
        for text in ("Short and sweet", "5 < 6 and 7 > 2"):
            with self.subTest(text=text):
                self.assertEqual(text, ui_helpers.tooltip_text(text))

    def test_markup_in_a_SHORT_tooltip_draws_as_text_not_as_html(self):
        """Qt auto-detects rich text; short remote markup draws as text. ▸r/tooltip-autodetect"""
        from PySide6 import QtGui
        from amaze.helpers import ui_helpers
        hostile = '<img src="http://evil.invalid/beacon.png">'
        out = ui_helpers.tooltip_text(hostile)

        document = QtGui.QTextDocument()
        document.setHtml(out)
        self.assertEqual(
            hostile, document.toPlainText(),
            "the tooltip renders the catalogue's markup instead of "
            "showing it, so an <img> loads a URL the catalogue chose")
        record = "\n".join(["<b>Free</b> Brick", "by <i>nobody</i>", "CC0"])    # the real sink
        document.setHtml(ui_helpers.tooltip_text(record))
        self.assertIn("<b>Free</b> Brick", document.toPlainText())

    def test_a_long_tooltip_becomes_a_width_capped_table(self):
        from amaze.helpers import ui_helpers
        self._with_dpr(1.0)
        long = ("This explanation goes on and on, well past any "
                "reasonable single line of screen, because it has a "
                "lot of genuinely useful things to say about what the "
                "switch does and when a person would want it off.") * 2
        wrapped = ui_helpers.tooltip_text(long)
        self.assertIn('width="800"', wrapped,
                      "the long tooltip is not capped at 800px")
        self.assertTrue(wrapped.startswith("<qt>"),
                        "not rich text - Qt will not wrap it")
        self.assertIn("<br><br>Second paragraph.",
                      ui_helpers.tooltip_text(long + "\n\nSecond paragraph."),
                      "rich text lost the paragraph break")

    def test_the_cap_is_real_pixels_not_logical(self):
        """On a 2x screen the 800 real-pixel cap is 400 logical, so a 720-logical sentence wraps."""
        from amaze.helpers import ui_helpers
        self._with_dpr(2.0)
        reported = ("Show files Amaze cannot thumbnail in the File "
                    "section, with their system icon. Off = the File "
                    "section shows only images, geometry and scene "
                    "files.")
        wrapped = ui_helpers.tooltip_text(reported)
        self.assertTrue(wrapped.startswith("<qt>"),
                        "the reported tooltip still draws as one "
                        "plain unwrapped line on a 2x screen")
        self.assertIn('width="400"', wrapped,
                      "the cap did not divide out the 2x ratio - "
                      "800 logical is 1600 real pixels on that screen")


class EveryDelegateCapsTheTooltipsOfItsItems(unittest.TestCase):
    """Models return plain text; the tile, list cell and sidebar row delegates wrap it at the cap."""

    def _shown(self, delegate, words):
        """The text `delegate` passes to QToolTip for an item whose tooltip is `words`, or None."""
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("x")
        item.setToolTip(words)
        model.appendRow(item)
        view = QtWidgets.QListView()
        view.setModel(model)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 200, 200)
        point = QtCore.QPoint(150, 150)
        event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, point, point)
        with mock.patch.object(QtWidgets.QToolTip, "showText") as show:
            delegate.helpEvent(event, view, option, model.index(0, 0))
        return show.call_args[0][1] if show.called else None

    def test_a_long_tooltip_wraps_and_markup_shows_as_text(self):
        from amaze.helpers import ui_helpers
        from amaze.panel import delegates
        long = "word " * 300
        hostile = '<img src="http://evil.invalid/beacon.png">'    # an Online title is remote text
        for delegate in (test_support.tile_delegate({}), delegates.GridCellDelegate(),
                         delegates.SidebarItemDelegate()):
            for words in (long, hostile):
                with self.subTest(delegate=type(delegate).__name__, words=words[:10]):
                    self.assertEqual(ui_helpers.tooltip_text(words),
                                     self._shown(delegate, words))


class StarColourRowsAreNotInPreferencesTest(unittest.TestCase):
    """The badges draw the star as drawn, so the star-colour rows and keys left the preferences."""

    def test_every_key_the_settings_code_does_not_know_is_kept_by_a_save(self):
        """save() leaves a key it does not know as it is: no list of older names is kept."""
        import json
        p = test_support.fixture_prefs(self)
        p.save()
        final = p.path + "/settings.json"
        with open(final, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw["star_color_mode"] = "custom"
        raw["star_custom_color"] = "#123456"
        raw["texture_folders"] = ["/tex/a/"]
        raw["geometry_favorites"] = ["/geo/c/rock.bgeo"]
        raw["hip_include_subfolders"] = True
        raw["file_section_migrated"] = True
        raw["key_from_a_newer_build"] = "kept"
        with open(final, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=4)
        p.save()
        with open(final, encoding="utf-8") as handle:
            after = json.load(handle)
        for key in ("star_color_mode", "star_custom_color", "texture_folders",
                    "geometry_favorites", "hip_include_subfolders", "file_section_migrated",
                    "key_from_a_newer_build"):
            self.assertEqual(raw[key], after.get(key),
                             "%s was changed or removed by a save" % key)


class MultiLineTooltipsAreCappedTest(unittest.TestCase):
    """A multi-line tooltip set in code goes through the width cap."""

    def test_every_dialog_tooltip_goes_through_the_cap(self):
        """Reads the source: a multi-line setToolTip without `tooltip_text` is screen-wide again."""
        import re
        package = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ("panel/panel.py",):
            with open(os.path.join(package, name),
                      encoding="utf-8") as handle:
                body = handle.read()
            for match in re.finditer(r"\.setToolTip\(\s*\n", body):
                line = body.count("\n", 0, match.start()) + 1
                if "tooltip_text" not in body[
                        match.start():match.end() + 40]:
                    offenders.append("%s:%d" % (name, line))
        self.assertEqual([], offenders,
                         "multi-line tooltips bypass the width cap: "
                         "%s" % offenders)


class LocationManagementTest(unittest.TestCase):
    """Removal drops thumbnails, a location lists its own folder, names default to the path and rename."""

    def _folders_model(self, *paths):
        prefs = _Prefs(list(paths))
        return file_library.FileFolders(prefs), prefs

    def _tmpdir(self, prefix="amaze_loc_"):
        tmp = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp

    def test_a_location_lists_every_file_in_its_own_folder_and_none_below(self):
        first = self._tmpdir()
        second = self._tmpdir()
        for base in (first, second):
            sub = os.path.join(base, "sub")
            os.makedirs(sub)
            for name in (os.path.join(sub, "buried.txt"), os.path.join(base, "top.txt"),
                         os.path.join(base, "top.png"), os.path.join(base, ".hidden")):
                with open(name, "w") as handle:
                    handle.write("x")
        prefs = _Prefs([first, second])
        model = file_library.FileFiles(prefs)
        model.set_folder(first)
        self.assertEqual(["top.png", "top.txt"],
                         sorted(model.data(model.index(row, 0)) for row in range(model.rowCount())),
                         "a location does not list exactly the files in its own folder")
        model.set_folder(os.path.join(first, "sub"))
        self.assertEqual(1, model.rowCount(), "a folder below a location does not list its file")
        model.set_all_folders()
        self.assertEqual(4, model.rowCount(), "All does not list each location's own files")
        folders_model = file_library.FileFolders(prefs)
        self.assertEqual([4, 2, 2], _wait_for_counts(folders_model),
                         "the sidebar counts differ from what the grid lists")

    def test_a_sidebar_paint_reads_the_location_list_once(self):
        """One read of the list serves a whole paint, and a write outside the model still shows."""
        model, prefs = self._folders_model(
            *[self._tmpdir() for _ in range(5)])
        self.assertEqual(6, model.rowCount(), "premise: five locations and All")
        reads = []
        real = locations_mod.registered_paths
        roles = (QtCore.Qt.ItemDataRole.DisplayRole,
                 QtCore.Qt.ItemDataRole.ToolTipRole, model.PathRole)
        with mock.patch.object(locations_mod, "registered_paths",
                               lambda p: (reads.append(1), real(p))[1]):
            for _paint in range(2):
                for row in range(model.rowCount()):
                    for role in roles:
                        model.data(model.index(row, 0), role)
            self.assertEqual([], reads, "two paints re-read the location "
                                        "list %d times" % len(reads))
            prefs.add_file_folder(self._tmpdir())
            self.assertEqual(7, model.rowCount(),
                             "a location registered outside the model "
                             "is not in the model")

    def test_a_sidebar_paint_reads_each_location_record_once(self):
        """A name and a colour per row per paint come from one read per location, and an edit shows."""
        from amaze.core import category
        folders = [self._tmpdir() for _ in range(5)]
        model, prefs = self._folders_model(*folders)
        prefs.set_file_folder_name(folders[0], "Renamed")
        roles = (QtCore.Qt.ItemDataRole.DisplayRole,
                 category.SIDEBAR_COLOR_ROLE)

        def paint():
            return [[model.data(model.index(row, 0), role) for role in roles]
                    for row in range(1, model.rowCount())]

        reads = []
        real = locations_mod.record
        with mock.patch.object(locations_mod, "record",
                               lambda p, path: (reads.append(path),
                                                real(p, path))[1]):
            first = paint()
            paint()
            self.assertEqual(5, len(reads), "two paints of five locations "
                             "read %d records" % len(reads))
            self.assertEqual(["Renamed", ""], first[0],
                             "the paint lost the stored name")
            prefs.set_file_folder_color(folders[1], "#e0523a")
            self.assertEqual("#e0523a", paint()[1][1],
                             "a colour set outside the model never showed")

    def test_a_record_another_machine_wrote_shows_after_a_reread(self):
        """After `model_registry.refresh_all` the next paint shows another writer's name and colour."""
        from amaze.core import category, library_db
        folders = [self._tmpdir() for _ in range(2)]
        model, prefs = self._folders_model(*folders)
        prefs.set_file_folder_name(folders[0], "Mine")
        roles = (QtCore.Qt.ItemDataRole.DisplayRole,
                 category.SIDEBAR_COLOR_ROLE)

        def paint():
            return [model.data(model.index(1, 0), role) for role in roles]

        self.assertEqual(["Mine", ""], paint(), "premise: the stored name")
        key = locations_mod.LOC_PREFIX + locations_mod.location_id(
            prefs, folders[0])
        library_db.flush(prefs)
        path = os.path.join(prefs.dir, locations_mod.FILES)
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        mine = document[locations_mod.LOCATIONS][str(prefs.library_user)]
        mine[key] = dict(mine[key], name="Theirs", color="#e0523a")
        with open(path, "w", encoding="utf-8") as handle:    # another machine's save
            json.dump(document, handle)
        self.assertEqual(["Mine", ""], paint(),
                         "premise: the file was read again before `refresh_all`")
        from amaze.core import model_registry
        self.assertIn(locations_mod.FILES, model_registry.refresh_all(prefs),
                      "premise: `refresh_all` did not reread the locations file")
        self.assertEqual(["Theirs", "#e0523a"], paint(),
                         "the sidebar kept the record from before the reread")

    def test_with_counts_off_all_still_shows_the_total(self):
        """With counts off, All still shows its total once the paint's folder walks finish."""
        from amaze.panel import delegates
        folders = [self._tmpdir() for _ in range(3)]
        for n, folder in enumerate(folders):
            for i in range(n + 2):
                open(os.path.join(folder, "f%d.png" % i), "w").close()
        model, _prefs = self._folders_model(*folders)
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        delegate = delegates.SidebarItemDelegate(view)
        delegate.show_counts = False
        view.setItemDelegate(delegate)
        view.setModel(model)
        view.resize(260, 400)
        view.show()
        for _paint in range(3):
            view.grab()
        self.assertTrue(test_support.pump_until(lambda: not model._walking),
                        "the folder walks the paint started never finished")
        texts = []
        for row in range(model.rowCount()):
            option = QtWidgets.QStyleOptionViewItem()
            option.widget = view
            option.font = view.font()
            delegate.initStyleOption(option, model.index(row, 0))
            texts.append(option.text)
        self.assertEqual("All (9)", texts[0],
                         "All lost its total with counts off: %s" % texts)
        self.assertEqual([model.display_name(path) for path in model._folders()],
                         texts[1:], "a hidden count was shown")

    def test_a_rename_sets_the_name_and_an_empty_rename_clears_it(self):
        model, prefs = self._folders_model("/assets/textures/")
        prefs.set_file_folder_name("/assets/textures/", "Set Dressing")
        self.assertEqual("Set Dressing", model.data(
            model.index(1, 0), QtCore.Qt.ItemDataRole.DisplayRole))
        prefs.set_file_folder_name("/assets/textures/", "")
        label = model.data(model.index(1, 0),
                           QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertIn("textures", label,
                      "clearing the name did not fall back to the path")

    def test_locate_keeps_the_name(self):
        old = self._tmpdir()
        new = self._tmpdir()
        model, prefs = self._folders_model(old)
        prefs.set_file_folder_name(old, "Set Dressing")
        prefs.save = lambda: None
        rewritten = model.relocate_folder(1, new)
        self.assertGreaterEqual(rewritten, 0, "relocate_folder failed")
        new_key = hostos.canonical_path_key(new) + "/"    # canonical - the locations API's spelling
        self.assertEqual({new_key: "Set Dressing"},
                         prefs.file_folder_names,
                         "the custom name was not moved to the new path")

    def test_locate_moves_the_pointer_and_the_favourites(self):
        """Locate edits the row's path in place and rewrites favourites under the old path."""
        first = self._tmpdir()
        old = self._tmpdir()
        new = self._tmpdir()
        old_key = old if old.endswith("/") else old + "/"
        prefs = _prefs_with_settings(self, {})    # a REAL Prefs: a stub's own copy of the move code would test only the copy
        prefs.dir = self._tmpdir(prefix="amaze_loc_lib_")
        for folder in (first, old):
            prefs.add_file_folder(folder)
        for path in (old_key + "keep.exr", "/elsewhere/other.exr"):
            prefs.add_file_favorite(path)
        model = file_library.FileFolders(prefs)

        rewritten = model.relocate_folder(2, new)

        new_key = hostos.canonical_path_key(new) + "/"    # canonical on both sides - the API's spelling
        first = hostos.canonical_path_key(first)
        self.assertEqual(1, rewritten,
                         "Locate did not report the favourite it moved")
        self.assertEqual([first, new_key], list(prefs.file_folders),
                         "the registered path did not change, or the row "
                         "changed position")
        self.assertEqual(sorted(["/elsewhere/other.exr",    # sorted: the favourites are a keyed store, read only as membership
                                 new_key + "keep.exr"]),
                         sorted(prefs.file_favorites),
                         "a favourite under the moved location was left "
                         "pointing at the old path")

    def test_removal_sweeps_the_cache_but_not_captures(self):
        """Removal deletes the folder's thumbnails, keeping covered files, bad manifests and captures."""
        import hashlib
        from amaze.helpers import hostos as hostos_mod

        removed_dir = self._tmpdir()
        kept_dir = self._tmpdir()
        cache_root = hostos_mod.cache_root()
        cache_dir = os.path.join(cache_root, "texture_thumbnails_256")
        os.makedirs(cache_dir, exist_ok=True)

        def entry(folder, name):
            path = hostos_mod.canonical_path_key(
                os.path.join(folder, name))
            png = os.path.join(
                cache_dir,
                hashlib.sha1(path.encode()).hexdigest() + ".png")
            with open(png, "wb") as handle:
                handle.write(b"png")
            return path, png

        removed_path, removed_png = entry(removed_dir, "a.png")
        kept_path, kept_png = entry(kept_dir, "b.png")
        manifest = {removed_path: {"mtime": 1, "size": 3},
                    kept_path: {"mtime": 1, "size": 3}}
        with open(os.path.join(cache_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        self.addCleanup(shutil.rmtree, cache_dir, ignore_errors=True)

        bad_dir = os.path.join(cache_root, "geo_thumbnails_bad_black_256")    # an unreadable sibling manifest must be left alone entirely
        os.makedirs(bad_dir, exist_ok=True)
        with open(os.path.join(bad_dir, "manifest.json"), "w") as f:
            f.write("{corrupt")
        self.addCleanup(shutil.rmtree, bad_dir, ignore_errors=True)

        prefs = _Prefs([])
        from amaze.core import captures    # a capture store with content that must be kept
        capture_dir = captures.folder(prefs)
        os.makedirs(capture_dir, exist_ok=True)
        marker = os.path.join(capture_dir, "sweep_canary.png")
        with open(marker, "wb") as handle:
            handle.write(b"capture")
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)

        removed = file_library.sweep_folder_cache(
            prefs, removed_dir, [kept_dir])
        self.assertEqual(1, removed)
        self.assertFalse(os.path.exists(removed_png),
                         "the removed folder's thumbnail was not deleted")
        self.assertTrue(os.path.exists(kept_png),
                        "another location's thumbnail was deleted")
        with open(os.path.join(cache_dir, "manifest.json")) as f:
            left = json.load(f)
        self.assertEqual([kept_path], list(left),
                         "the manifest does not match the deletions")
        with open(os.path.join(bad_dir, "manifest.json")) as f:
            self.assertEqual("{corrupt", f.read(),
                             "an unreadable manifest was rewritten")
        self.assertTrue(os.path.exists(marker),
                        "sweep_folder_cache changed the capture store")

    def test_a_swept_entry_stays_gone_when_the_live_cache_saves(self):
        """The grid's own cache object held the removed folder's entries, saved and unsaved."""
        from amaze.core import texture_library
        removed_dir = self._tmpdir()
        kept_dir = self._tmpdir()
        image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("red"))

        def source(folder, name):
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(b"x")
            return hostos.canonical_path_key(path)

        saved, unsaved = (source(removed_dir, n) for n in ("a.png", "b.png"))
        kept, later = (source(kept_dir, n) for n in ("c.png", "d.png"))
        cache = texture_library.ThumbnailCache(
            256, prefix="texture_thumbnails_sweep_live")
        self.addCleanup(shutil.rmtree, cache.cache_dir, ignore_errors=True)
        cache.put(saved, image)
        cache.put(kept, image)
        cache.save()
        cache.put(unsaved, image)
        prefs = _Prefs([])
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)

        file_library.sweep_folder_cache(prefs, removed_dir, [kept_dir])
        cache.put(later, image)
        cache.save()

        with open(cache.manifest_path, encoding="utf-8") as handle:
            on_disk = sorted(json.load(handle))
        self.assertEqual(
            sorted([kept, later]), on_disk,
            "the live cache wrote the removed folder's entries back on "
            "its next save")
        self.assertFalse(
            os.path.exists(os.path.join(
                cache.cache_dir, cache._cache_filename(unsaved))),
            "a thumbnail the live cache had not saved yet was not deleted by "
            "sweep_folder_cache")

    def test_remove_folder_drops_the_per_location_state(self):
        """All four per-location settings are read afterwards, not checked by mocking setters."""
        tmp = self._tmpdir()
        kept = self._tmpdir()    # two locations, so the assertions read the survivor
        model, prefs = self._folders_model(tmp, kept)
        for path, name, colour in ((tmp, "Custom", "#ff8000"), (kept, "Kept", "#0080ff")):
            prefs.set_file_folder_name(path, name)
            prefs.set_file_folder_color(path, colour)
        prefs.save = lambda: None
        from unittest import mock
        with mock.patch.object(
                file_library, "sweep_folder_cache") as sweep:
            model.remove_folder(1)
        kept = hostos.canonical_path_key(kept)    # canonical - mkdtemp made these natively
        tmp = hostos.canonical_path_key(tmp)
        self.assertEqual({kept: "Kept"}, prefs.file_folder_names,
                         "the custom name was not removed with its folder, or the "
                         "removal changed the location NEXT to it")
        self.assertEqual(
            {kept: "#0080ff"}, prefs.file_folder_colors,
            "the location's COLOUR was not removed with its folder, so re-adding "
            "the same path shows it amber again with no message that "
            "the colour was kept - or the removal also deleted the neighbour's "
            "colour")
        sweep.assert_called_once_with(prefs, tmp, [kept])


def _wait_for_counts(model, timeout=10.0):
    """Every row's count, All first, once no walk is queued or running; a paint only requests."""
    from amaze.core import category
    deadline = time.monotonic() + timeout
    while True:
        counts = [model.data(model.index(row, 0), category.SIDEBAR_COUNT_ROLE)
                  for row in range(model.rowCount())]
        if not getattr(model, "_walking", None) and None not in counts:
            return counts
        if time.monotonic() > deadline:
            raise AssertionError("the counts never landed: %s" % counts)
        _app.processEvents()
        time.sleep(0.002)


def _norm(path) -> str:
    """One spelling of a path, so a recorded call matches whatever separators the model passed."""
    return os.path.normcase(os.path.normpath(str(path)))


def _same_path(path, other) -> bool:
    return _norm(path) == _norm(other)


def _under(path, root) -> bool:
    """`path` is `root` or inside it, compared by `_norm` - a raw startswith misses on Windows."""
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


class CountsWalkOffTheGuiThreadTest(unittest.TestCase):
    """The File sidebar's counts are computed on a worker; a paint returns what is known now."""

    def _model(self, *sizes):
        """A sidebar over one fresh location per size, holding that many images each."""
        roots = []
        for size in sizes:
            root = tempfile.mkdtemp(prefix="amaze_walk_")
            self.addCleanup(shutil.rmtree, root, ignore_errors=True)
            for i in range(size):
                open(os.path.join(root, "f%d.png" % i), "w").close()
            roots.append(root)
        prefs = _Prefs(roots)
        model = file_library.FileFolders(prefs)
        self.addCleanup(lambda: test_support.pump_until(
            lambda: not getattr(model, "_walking", None)))
        return model, roots

    def _blocked_listing(self, blocked_root):
        """An `os.scandir` that blocks a WORKER inside one location until released."""
        main = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        real = os.scandir

        def listing(path="."):
            if (threading.get_ident() != main
                    and _same_path(path, blocked_root)):
                entered.set()
                release.wait(10)
            return real(path)
        return listing, entered, release

    def test_a_paint_walks_no_folder_on_the_gui_thread(self):
        from amaze.panel import delegates
        model, roots = self._model(2, 3)
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        view.setItemDelegate(delegates.SidebarItemDelegate(view))
        main = threading.get_ident()
        on_gui = []

        def watched(real):
            def call(path="."):
                if (threading.get_ident() == main
                        and any(_under(path, r) for r in roots)):
                    on_gui.append(str(path))
                return real(path)
            return call

        with mock.patch("os.listdir", watched(os.listdir)), \
                mock.patch("os.scandir", watched(os.scandir)):
            view.setModel(model)    # inside: the size hints request counts too
            view.resize(260, 200)
            view.show()
            view.grab()
            counts = _wait_for_counts(model)
        self.assertEqual([], on_gui, "a paint read folders on the GUI thread")
        self.assertEqual([5, 2, 3], counts, "the counts are wrong")

    def test_counts_arrive_and_all_shows_the_total(self):
        from amaze.core import category
        model, _roots = self._model(2, 3, 4)
        changed = []
        model.dataChanged.connect(
            lambda first, last, roles=(): changed.append((first.row(), last.row())))
        first = [model.data(model.index(row, 0), category.SIDEBAR_COUNT_ROLE)
                 for row in range(model.rowCount())]
        self.assertEqual([None] * 4, first,
                         "a first paint returned counts only a walk could know")
        self.assertEqual([9, 2, 3, 4], _wait_for_counts(model),
                         "the counts or the All total did not arrive")
        for row in (0, 1, 2, 3):
            self.assertIn((row, row), changed,
                          "row %d never got dataChanged for its count" % row)

    def test_a_blocked_location_delays_no_other_count(self):
        """A hung share blocks only its own worker; every other location's count still arrives."""
        model, roots = self._model(*[1] * 8)
        blocked_key = model._folders()[0]
        others = model._folders()[1:]
        listing, entered, release = self._blocked_listing(roots[0])
        with mock.patch("os.scandir", listing):
            for row in range(1, model.rowCount()):
                model.data(model.index(row, 0), model.COUNT_ROLE)
            counted = test_support.pump_until(
                lambda: all(model._counts.get(p) == 1 for p in others), timeout=5.0)
            self.assertTrue(entered.is_set(), "premise: the held walk never ran on a worker")
            self.assertIsNone(model._counts.get(blocked_key),
                              "premise: the blocked location's count arrived while blocked")
            waiting = [p for p in others if model._counts.get(p) is None]
            release.set()
            counts = _wait_for_counts(model)
        self.assertTrue(counted, "%d location(s) had no count while another walked: %s"
                        % (len(waiting), waiting))
        self.assertEqual([8] + [1] * 8, counts, "the counts are wrong")

    def test_a_location_removed_mid_walk_keeps_no_count(self):
        model, roots = self._model(2, 3)
        removed = model._folders()[0]
        listing, entered, release = self._blocked_listing(roots[0])
        with mock.patch("os.scandir", listing):
            model.data(model.index(1, 0), model.COUNT_ROLE)
            self.assertTrue(test_support.pump_until(entered.is_set),
                            "the walk never ran on a worker")
            self.assertTrue(model.remove_folder(1), "premise: remove_folder failed")
            release.set()
            counts = _wait_for_counts(model)
        self.assertEqual([3, 3], counts, "All or the surviving row is wrong")
        self.assertNotIn(removed, model._counts,
                         "the removed location kept the count its walk brought back")

    def test_a_count_walked_before_a_refresh_is_dropped(self):
        """A file arrives mid-walk and the counts are refreshed: that walk's result is dropped."""
        root = tempfile.mkdtemp(prefix="amaze_walk_rule_")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        open(os.path.join(root, "a.png"), "w").close()
        prefs = _Prefs([root])
        model = file_library.FileFolders(prefs)
        key = model._folders()[0]
        shown = []
        model.dataChanged.connect(
            lambda first, last, roles=(): shown.append(model._counts.get(key)))
        listing, entered, release = self._blocked_listing(root)
        with mock.patch("os.scandir", listing):
            model.data(model.index(1, 0), model.COUNT_ROLE)
            self.assertTrue(test_support.pump_until(entered.is_set),
                            "the walk never ran on a worker")
            real_open = open
            real_open(os.path.join(root, "b.xyz"), "w").close()
            model.refresh_counts()
            release.set()
            counts = _wait_for_counts(model)
        self.assertEqual([2, 2], counts,
                         "a count walked before the refresh was kept")
        self.assertNotIn(1, shown, "the earlier walk's count was emitted with dataChanged")

    def test_a_relocate_recounts_only_that_location(self):
        model, roots = self._model(1, 2, 3)
        _wait_for_counts(model)
        new = tempfile.mkdtemp(prefix="amaze_walk_moved_")
        self.addCleanup(shutil.rmtree, new, ignore_errors=True)
        for i in range(4):
            open(os.path.join(new, "g%d.png" % i), "w").close()
        model.preferences.save = lambda: None
        walked = []
        real = os.scandir

        def listing(path="."):
            if any(_under(path, r) for r in roots + [new]):
                walked.append(_norm(path))
            return real(path)

        with mock.patch("os.scandir", listing):
            self.assertGreaterEqual(model.relocate_folder(2, new), 0,
                                    "premise: Locate failed")
            counts = _wait_for_counts(model)
        self.assertEqual([8, 1, 4, 3], counts, "the moved location's count is wrong")
        self.assertEqual([_norm(new)], walked,
                         "a Locate recounted locations it did not move")

    def test_a_count_requested_from_another_thread_still_arrives(self):
        """hrpyc reads models off the GUI thread; a zero-timer started there never fires."""
        model, _roots = self._model(5)
        asker = threading.Thread(
            target=lambda: model.data(model.index(1, 0), model.COUNT_ROLE))
        asker.start()
        asker.join(10)
        self.assertTrue(test_support.pump_until(lambda: model._counts.get(model._folders()[0]) == 5),
                        "a count requested from another thread never arrived")
        self.assertEqual([5, 5], _wait_for_counts(model),
                         "the sidebar stopped counting after a request from another thread")

    def test_a_shutdown_starts_none_of_the_queued_walks(self):
        """Stopped walks start no queued walk; a later request still counts every location."""
        from amaze.core import folders as folders_mod
        model, roots = self._model(*[1] * 6)
        main = threading.get_ident()
        walked = []
        real = os.scandir

        def listing(path="."):
            if (threading.get_ident() != main
                    and any(_under(path, r) for r in roots)):
                walked.append(str(path))
                thread = QtCore.QThread.currentThread()
                deadline = time.monotonic() + 3
                while not thread.isInterruptionRequested() and time.monotonic() < deadline:
                    time.sleep(0.005)    # held until the shutdown stops it
            return real(path)

        with mock.patch("os.scandir", listing):
            for row in range(1, model.rowCount()):
                model.data(model.index(row, 0), model.COUNT_ROLE)
            self.assertTrue(test_support.pump_until(lambda: len(walked) == model.COUNT_WORKERS),
                            "premise: the workers never all started")
            folders_mod.counter.shutdown()
            test_support.pump_until(
                lambda: False, timeout=0.3)    # every stopped walk's end is handled
            started = list(walked)
        self.assertEqual(model.COUNT_WORKERS, len(started),
                         "the stopped walks started the queued ones after the shutdown")
        self.assertEqual([6] + [1] * 6, _wait_for_counts(model),
                         "after a shutdown the counts never arrived")


class RemovingANestedLocationTest(unittest.TestCase):
    """A file a remaining location still lists keeps its comment, star and icon."""

    ICON = {"name": "activity", "bg": "#ff8000"}
    OTHER = "0123456789abcdef0123456789abcdef"

    def setUp(self):
        self.outer = tempfile.mkdtemp(prefix="amaze_outer_")
        self.addCleanup(shutil.rmtree, self.outer, ignore_errors=True)
        self.inner = os.path.join(self.outer, "tex")
        self.file = os.path.join(self.inner, "plate.txt")
        os.makedirs(self.inner)
        with open(self.file, "w") as handle:
            handle.write("x")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)

    def _nested(self, *folders):
        prefs = _Prefs(folders)
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)
        return prefs

    def _row(self, prefs, folder):
        model = file_library.FileFiles(prefs)
        model.set_folder(folder)
        names = [model.data(model.index(row, 0)) for row in
                 range(model.rowCount())]
        return model, names.index("plate.txt")

    def _annotate(self, prefs):
        from amaze.core import notes
        model, row = self._row(prefs, self.inner)
        key = model.file_key(row)
        model.toggle_favorite(row)
        model.set_tile_icon(row, self.ICON)
        notes.set_note(prefs, notes.note_key("file", key),
                       [{"t": "text", "text": "kept"}])
        return key

    def _shown(self, prefs, folder):
        model, row = self._row(prefs, folder)
        index = model.index(row, 0)
        return (model.data(index, model.FavoriteRole),
                model.data(index, model.NotesRole),
                model.tile_icon(row).get("name"))

    def _remove(self, prefs, folder):
        listed = [hostos.canonical_path_key(p) for p in prefs.file_folders]
        file_library.FileFolders(prefs).remove_folder(
            listed.index(hostos.canonical_path_key(folder)) + 1)
        self.assertNotIn(
            hostos.canonical_path_key(folder),
            [hostos.canonical_path_key(p) for p in prefs.file_folders],
            "premise: the location is still registered")

    def test_a_location_added_inside_another_keeps_the_comment_star_and_icon(self):
        from amaze.core import library_db
        prefs = self._nested(self.outer)
        old = self._annotate(prefs)
        self.assertEqual((True, True, "activity"), self._shown(prefs, self.inner),
                         "premise: the file under the outer location is not annotated")
        held = library_db.document(prefs, locations_mod.FILES)
        prefs.library_user = self.OTHER    # another user of the library stars the same file
        held.put_mine(locations_mod.FAVORITES, old, True)
        library_db.save(prefs, locations_mod.FILES)
        prefs.library_user = test_support.FIXTURE_USER
        prefs.add_file_folder(self.inner)
        self.assertEqual(
            (True, True, "activity"), self._shown(prefs, self.inner),
            "a file's star, comment or icon was not found once its folder became a location")
        model, row = self._row(prefs, self.inner)
        self.assertNotEqual(old, model.file_key(row), "premise: the file kept its key")
        self.assertEqual({model.file_key(row): True},
                         held.everyones(locations_mod.FAVORITES).get(self.OTHER),
                         "another user's favorite stayed under the key the file no longer has")

    def test_a_second_session_adding_the_same_folder_uses_the_first_one_s_id(self):
        from amaze.core import documents, library_db
        prefs = self._nested()
        library_db.document(prefs, locations_mod.FILES)    # read before the other session saves
        other = documents.Library(prefs.dir, self.OTHER).document(locations_mod.FILES)
        other.put(locations_mod.PATHS, "0" * 32, {"path": hostos.storage_path_key(self.inner)})
        self.assertTrue(other.save())
        prefs.add_file_folder(self.inner)
        held = library_db.document(prefs, locations_mod.FILES)
        self.assertEqual(["0" * 32], sorted(held.table(locations_mod.PATHS)),
                         "one folder got a second location id")

    def test_two_ids_for_one_folder_become_one_and_every_key_follows(self):
        from amaze.core import library_db
        prefs = self._nested(self.inner)
        self._annotate(prefs)
        held = library_db.document(prefs, locations_mod.FILES)
        mine = locations_mod.location_id(prefs, self.inner)
        twin = "0" * 32 if mine != "0" * 32 else "1" * 32    # sorts first, so it is the one kept
        self.assertTrue(held.put(locations_mod.PATHS, twin,
                                 {"path": hostos.storage_path_key(self.inner)}))
        prefs.library_user = self.OTHER    # the other session's user registered it under its own id
        held.put_mine(locations_mod.LOCATIONS, "loc:" + twin, {"registered": True})
        held.put_mine(locations_mod.FAVORITES, "loc:" + twin + "/plate.txt", True)
        library_db.save(prefs, locations_mod.FILES)
        prefs.library_user = test_support.FIXTURE_USER
        locations_mod.touch()

        self.assertEqual(1, locations_mod.fold_duplicate_ids(prefs))

        self.assertEqual([twin], sorted(held.table(locations_mod.PATHS)))
        self.assertEqual((True, True, "activity"), self._shown(prefs, self.inner),
                         "the star, comment or icon stayed under the id that was dropped")
        everyone = held.everyones(locations_mod.LOCATIONS)
        self.assertEqual([["loc:" + twin], ["loc:" + twin]],
                         [sorted(everyone[user]) for user in sorted(everyone)])
        self._remove(prefs, self.inner)

    def test_the_outer_location_keeps_the_comment_star_and_icon(self):
        prefs = self._nested(self.outer, self.inner)
        key = self._annotate(prefs)
        inner_id = locations_mod.location_id(prefs, self.inner)
        self.assertTrue(key.startswith("loc:" + inner_id + "/"),
                        "premise: the nested location does not own the file")
        from amaze.core import library_db
        prefs.library_user = self.OTHER
        locations_mod.set_favourite(prefs, key, True)
        prefs.library_user = test_support.FIXTURE_USER

        self._remove(prefs, self.inner)

        self.assertEqual(
            (True, True, "activity"), self._shown(prefs, self.inner),
            "removing the nested location retired the star, comment or "
            "icon of a file the outer location still covers")
        stars = library_db.document(prefs, locations_mod.FILES).everyones(locations_mod.FAVORITES)
        self.assertIn(key, stars.get(self.OTHER, {}),
                      "another user's star on that file was retired")

    def test_a_location_nothing_else_covers_still_loses_them(self):
        from amaze.core import notes
        prefs = self._nested(self.inner)
        key = self._annotate(prefs)

        self._remove(prefs, self.inner)

        self.assertEqual(
            (False, False, {}),
            (locations_mod.is_favourite(prefs, key),
             notes.has_note(prefs, notes.note_key("file", key)),
             tile_icons.override_for(prefs, key, locations_mod.FILES)),
            "a removed location no other location covers kept a star, "
            "comment or icon, so re-adding it does not start empty")

    def test_a_failed_move_unregisters_nothing(self):
        prefs = self._nested(self.outer, self.inner)
        self._annotate(prefs)
        with mock.patch.object(locations_mod, "files_moved", lambda *_a: False):
            self._remove(prefs, self.inner)

        self.assertEqual(
            (True, True, "activity"), self._shown(prefs, self.inner),
            "a comment that could not move was retired anyway")

    def test_a_key_spelled_as_a_path_moves_too(self):
        from amaze.core import library_db, notes
        prefs = self._nested(self.outer, self.inner)
        spelled = hostos.storage_path_key(self.file)
        held = library_db.document(prefs, locations_mod.FILES)
        held.put_mine(locations_mod.FAVORITES, spelled, True)
        library_db.save(prefs, locations_mod.FILES)
        notes.set_note(prefs, notes.note_key("file", spelled), [{"t": "text", "text": "kept"}])
        tile_icons.set_override(prefs, spelled, self.ICON, locations_mod.FILES)

        self.assertTrue(locations_mod.rekey_to_covering_location(prefs, self.inner))

        moved = ("loc:" + locations_mod.location_id(prefs, self.outer)
                 + "/tex/plate.txt")
        self.assertEqual(
            [True, True, True],
            [moved in held.mine(locations_mod.FAVORITES),
             moved in held.table(locations_mod.COMMENTS),
             moved in held.table(locations_mod.ICONS)],
            "a path-spelled key the outer location covers was not moved "
            "before the retire")


class TheFolderOrderHasOneSpellingTest(unittest.TestCase):
    """Locations under home store as `~/...`; the order copy must match them however it was written."""

    def setUp(self):
        self.home = hostos.canonical_path_key(
            tempfile.mkdtemp(prefix="amaze_home_"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        patcher = mock.patch.object(hostos, "_home_root",
                                    return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _under_home(self, name):
        path = os.path.join(self.home, name)
        os.makedirs(path)
        return path

    def _listed(self, prefs):
        return [hostos.canonical_path_key(p) for p in prefs.file_folders]

    def test_an_offline_remove_takes_the_row_off(self):
        prefs, library = _location_prefs(self, {})
        folder = self._under_home("tex")
        prefs.add_file_folder(folder)
        self.assertIn(hostos.canonical_path_key(folder), self._listed(prefs),
                      "premise: the location did not register")
        locations_mod.forget()
        prefs.dir = os.path.join(library, "not-mounted")
        self.assertTrue(locations_mod.showing_last_known(prefs),
                        "premise: the library is still reachable")
        prefs.remove_file_folder(folder)
        self.assertNotIn(
            hostos.canonical_path_key(folder), self._listed(prefs),
            "removing a location while the library is unreachable left "
            "its row - the order copy holds another spelling of it")

    def test_with_no_library_no_settings_row_is_left_to_remove(self):
        prefs = _prefs_with_settings(self, {
            "directory": "",
            "file_folders": ["~/tex/"],
            "file_location_records": {"~/tex/": {"registered": True}},
        })
        self._under_home("tex")
        self.assertEqual([], self._listed(prefs),
                         "a location read back from settings shows with no library, "
                         "where it cannot be removed")

    def test_locate_after_a_reorder_keeps_the_row(self):
        prefs, _library = _location_prefs(self, {})
        for name in ("a", "b", "c"):
            prefs.add_file_folder(self._under_home(name))
        model = file_library.FileFolders(prefs)
        self.assertTrue(model.move_folder(3, 1), "premise: no reorder")
        moved = self._under_home("c_moved")
        self.assertGreaterEqual(model.relocate_folder(1, moved), 0,
                                "premise: Locate failed")
        self.assertEqual(
            hostos.canonical_path_key(moved), self._listed(prefs)[0],
            "Locate after a reorder dropped the location to the bottom "
            "of the sidebar")


class ALocationWriteIsAnnouncedOnlyWhenItSucceedsTest(unittest.TestCase):
    """The sidebar is notified of a row change only after its prefs write succeeded."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="amaze_landed_")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        with open(os.path.join(self.folder, "plate.txt"), "w") as handle:
            handle.write("x")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        self.prefs = _Prefs([self.folder])
        self.addCleanup(shutil.rmtree, self.prefs.dir, ignore_errors=True)
        self.model = file_library.FileFolders(self.prefs)
        self.signals = []
        for name in ("rowsAboutToBeInserted", "rowsInserted",
                     "rowsAboutToBeRemoved", "rowsRemoved", "modelReset"):
            getattr(self.model, name).connect(
                lambda *args, name=name: self.signals.append(
                    (name, self.model.rowCount())))

    def _full_disk(self):
        return test_support.full_disk_for(os.path.join(self.prefs.dir, locations_mod.FILES))

    def _on_disk(self):
        with open(os.path.join(self.prefs.dir, locations_mod.FILES), encoding="utf-8") as handle:
            document = json.load(handle)
        user = str(self.prefs.library_user)
        return (sorted(document.get(locations_mod.LOCATIONS, {}).get(user, {})),
                sorted(document.get(locations_mod.FAVORITES, {}).get(user, {})))

    def test_a_failed_remove_waits_whole_and_is_written_as_one(self):
        from amaze.core import library_db
        files = file_library.FileFiles(self.prefs)
        files.set_folder(self.folder)
        files.toggle_favorite(0)
        library_db.flush()
        before = self._on_disk()
        self.assertTrue(before[0] and before[1], "premise: no location or star on disk")
        with self._full_disk():
            self.model.remove_folder(1)
            library_db.flush()
        self.assertEqual(before, self._on_disk(),
                         "a failed removal wrote part of its change")
        library_db.flush()
        self.assertEqual(([], []), self._on_disk(),
                         "the pending removal was not written in full once the disk had room")

    def test_a_successful_write_is_announced_around_the_change(self):
        other = tempfile.mkdtemp(prefix="amaze_landed_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertTrue(self.model.add_folder(other))
        self.assertTrue(self.model.remove_folder(1))
        self.assertEqual(
            [("rowsAboutToBeInserted", 2), ("rowsInserted", 3),
             ("rowsAboutToBeRemoved", 3), ("rowsRemoved", 2)],
            self.signals,
            "a row change was not bracketed: the model must return the "
            "old rows until the views are notified")


def _check_ui(*wanted_labels):
    """`hou.ui` for Check Library: each box picks the next wanted button by label, else close."""
    wanted, shown = list(wanted_labels), []

    def answer(text, *_args, **kwargs):
        shown.append(text)
        buttons = list(kwargs.get("buttons") or ())
        hit = [at for at, label in enumerate(buttons) if wanted and wanted[0] in label]
        if hit:
            wanted.pop(0)
            return hit[0]
        return kwargs.get("close_choice", 0)

    return mock.Mock(displayMessage=answer, selectFromList=lambda *a, **k: (), shown=shown)


class CheckLibraryResetsTheFolderModelTest(unittest.TestCase):
    """Missing locations leave the prefs, and the File model is reset before any box is shown."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_missing_locations_are_removed_with_a_structural_signal(self):
        panel = self.panel
        model = panel.file_folders_model
        missing_a, alive, missing_b = [
            tempfile.mkdtemp(prefix="amaze_cleanup_%s_" % name)
            for name in ("missing_a", "alive", "missing_b")
        ]
        for path in (missing_a, alive, missing_b):
            self.addCleanup(shutil.rmtree, path, ignore_errors=True)
            self.addCleanup(panel.prefs.remove_file_folder, path)
            model.add_folder(path)
        for path in (missing_a, missing_b):
            shutil.rmtree(path)

        events = []
        model.rowsRemoved.connect(lambda *_a: events.append("rows"))
        model.modelReset.connect(lambda: events.append("reset"))
        screen = _check_ui("Fix Safe")
        answer = screen.displayMessage

        def display_message(text, *args, **kwargs):
            if not kwargs.get("buttons"):
                events.append("said")
            return answer(text, *args, **kwargs)

        screen.displayMessage = display_message
        with mock.patch.object(hou, "ui", screen, create=True):
            test_support.repair_from_preferences(self, panel)

        self.assertIn("said", events, "premise: nothing was set aside")
        self.assertNotEqual("said", events[0], "the result box was shown before the model was reset, "
                                             "so a view paints a stale row count under it")
        survivors = list(panel.prefs.file_folders)
        self.assertIn(    # the locations API returns CANONICAL absolute paths, so the expectation converts too
            hostos.canonical_path_key(alive), survivors,
            "cleanup removed a location whose folder is still there")
        for path in (missing_a, missing_b):
            self.assertNotIn(
                hostos.canonical_path_key(path), survivors,
                "a missing location was not removed - the second removal "
                "used a row index the first one had already shifted")


class CheckLibraryReachesTheFoldersTest(unittest.TestCase):
    """Check Library reports registered folders too, not only asset lists, and sets them aside."""

    def test_a_missing_location_is_named_set_aside_and_reported(self):
        panel = test_support.fixture_panel(self)
        missing = tempfile.mkdtemp(prefix="amaze_missing_location_")
        self.addCleanup(shutil.rmtree, missing, ignore_errors=True)
        self.addCleanup(panel.prefs.remove_file_folder, missing)
        panel.file_folders_model.add_folder(missing)
        shutil.rmtree(missing)

        screen = _check_ui("Fix Safe")
        with mock.patch.object(hou, "ui", screen, create=True):
            test_support.repair_from_preferences(self, panel)

        self.assertNotIn(hostos.canonical_path_key(missing), list(panel.prefs.file_folders),
                         "Check Library left a location whose folder is gone")
        self.assertIn("1 folder in the Files section is gone.", screen.shown[0],
                      "the Repair dialog does not count the location")
        self.assertIn("1 folder removed from the Files section.", screen.shown,
                      "no message reports the location was set aside")


class CheckLibraryDropsOnlyFileStarsTest(unittest.TestCase):
    """The favourites store holds every section's stars; only a File one names a file to check."""

    def test_a_material_star_is_kept_and_a_missing_file_star_is_removed(self):
        panel = test_support.fixture_panel(self)
        model = panel.material_model
        mat_id = model.assets[1].mat_id    # row 0 is the fixture's odd id -1
        model.toggle_fav(1)
        self.assertTrue(locations_mod.is_favourite(panel.prefs, mat_id, model.DB_FILENAME),
                        "premise: the material star did not set")
        missing = os.path.join(panel.prefs.file_folders[0], "gone.exr")
        panel.prefs.add_file_favorite(missing)
        self.assertTrue(locations_mod.is_favourite(panel.prefs, missing),
                        "premise: the File star did not set")

        from amaze.core import repair
        findings = repair.survey(panel.prefs)
        lines = repair.report_lines(findings)
        repair.drop_favorites_of_missing_files(findings, guard_session=False)

        self.assertTrue(
            locations_mod.is_favourite(panel.prefs, mat_id, model.DB_FILENAME),
            "Check Library removed a material's star - its bare asset id "
            "was checked as a file path, and no file is named like an id")
        self.assertNotIn(str(mat_id), "\n".join(lines),
                         "the report lists a material id as a gone file")
        self.assertFalse(locations_mod.is_favourite(panel.prefs, missing),
                         "Check Library kept a favourite whose file is gone")

    def test_the_file_favourites_list_no_asset_star(self):
        prefs, _library = _location_prefs(self, {})
        folder = tempfile.mkdtemp(prefix="amaze_star_folder_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        prefs.add_file_folder(folder)
        plate = os.path.join(folder, "plate.exr")
        mat_id = "139888336268658010"
        self.assertTrue(locations_mod.set_favourite(prefs, mat_id, True, library_files.MATERIALS))
        self.assertTrue(locations_mod.set_favourite(prefs, plate, True))
        self.assertEqual([hostos.canonical_path_key(plate)],
                         [hostos.canonical_path_key(p) for p in prefs.file_favorites],
                         "the File favourites include a material id, or lost the file")


class CheckLibrarySetsAFolderMissingHereAsideTest(unittest.TestCase):
    """A folder missing HERE may be on another machine: it is unregistered, its files' data kept."""

    ICON = {"name": "activity", "bg": "#ff8000"}

    def setUp(self):
        from amaze.core import notes
        self.notes = notes
        self.root = tempfile.mkdtemp(prefix="amaze_set_aside_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.folder = os.path.join(self.root, "Textures")
        os.makedirs(self.folder)
        self.rock = os.path.join(self.folder, "rock.png")
        with open(self.rock, "wb") as handle:
            handle.write(b"png")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        self.prefs = _Prefs([self.folder])
        self.addCleanup(shutil.rmtree, self.prefs.dir, ignore_errors=True)
        self.model = file_library.FileFolders(self.prefs)
        self.lid = locations_mod.location_id(self.prefs, self.folder)
        self.key = locations_mod.file_ident(self.prefs, self.rock)
        self.assertTrue(self.lid and self.key.startswith("loc:" + self.lid + "/"),
                        "premise: the registered folder does not own its file")
        notes.set_note(self.prefs, notes.note_key("file", self.key),
                       [{"t": "text", "text": "approved by lighting"}])
        tile_icons.set_override(self.prefs, self.key, self.ICON, locations_mod.FILES)
        locations_mod.set_favourite(self.prefs, self.key, True)
        self.assertEqual((True, True, True), self._kept(), "premise: nothing was set")

    def _kept(self):
        return (self.notes.has_note(self.prefs, self.notes.note_key("file", self.key)),
                bool(tile_icons.override_for(self.prefs, self.key, locations_mod.FILES)),
                locations_mod.is_favourite(self.prefs, self.key))

    def _registered(self):
        return [hostos.canonical_path_key(p) for p in self.prefs.file_folders]

    def _clean_while_elsewhere(self):
        from amaze.core import repair
        os.rename(self.folder, self.folder + ".elsewhere")
        findings = dict(repair._files_section(self.prefs), preferences=self.prefs, leftovers=[])
        lines = repair.report_lines(dict(findings, directory=self.prefs.dir, lists=[],
                                         unreadable_folders=[], unaccounted={}, complete=True))
        repair.set_aside_folders(findings, guard_session=False)
        return lines

    def test_the_registration_is_removed_and_its_files_annotations_are_kept(self):
        lines = self._clean_while_elsewhere()
        self.assertNotIn(hostos.canonical_path_key(self.folder), self._registered(),
                         "Check Library kept the registration of a folder that is not here")
        self.assertEqual(self.lid, locations_mod.location_id(self.prefs, self.folder),
                         "the location's id was removed with its registration")
        self.assertEqual((True, True, True), self._kept(),
                         "comment, icon and star of a file in it were deleted")
        naming = [line for line in lines if os.path.basename(self.folder) in line]
        self.assertEqual(1, len(naming), lines)
        self.assertIn("aside", naming[0])
        self.assertIn("keeps its comments, icons and favorites", naming[0])
        self.assertNotIn("removed", naming[0])

    def test_the_folder_coming_back_shows_its_annotations_again(self):
        self._clean_while_elsewhere()
        os.rename(self.folder + ".elsewhere", self.folder)
        self.assertTrue(self.model.add_folder(self.folder), "premise: the folder was not re-added")
        self.assertEqual(self.key, locations_mod.file_ident(self.prefs, self.rock),
                         "the returning folder was given a new id")
        self.assertEqual((True, True, True), self._kept())

    def test_the_sidebar_remove_still_deletes_everything(self):
        row = self._registered().index(hostos.canonical_path_key(self.folder)) + 1
        self.assertTrue(self.model.remove_folder(row))
        self.assertEqual((False, False, False), self._kept(),
                         "Remove left a comment, an icon or a star behind")
        self.assertEqual("", locations_mod.location_id(self.prefs, self.folder))


class ALocationListsEveryKindOfFileTest(unittest.TestCase):
    """A location lists images, geometry, scenes and every other file, and stores no choice of them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_show_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name in ("a.png", "b.obj", "c.hip", "d.txt"):
            with open(os.path.join(self.tmp, name), "w") as handle:
                handle.write("x")
        self.prefs = _Prefs([self.tmp])

    def test_all_four_kinds_are_listed_and_counted(self):
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp)
        self.assertEqual(["a.png", "b.obj", "c.hip", "d.txt"],
                         sorted(model._files[row][1] for row in range(len(model._files))))
        self.assertEqual(4, _wait_for_counts(file_library.FileFolders(self.prefs))[1],
                         "the sidebar counts what the grid does not list")

    def test_a_record_holding_the_old_show_values_lists_the_same(self):
        locations_mod.set_record(self.prefs, self.tmp, {
            "registered": True, "kinds": ["image"], "recursive": True, "pathname": True})
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp)
        self.assertEqual(4, model.rowCount(), "an old `kinds` value still narrows the location")
        folders = file_library.FileFolders(self.prefs)
        self.assertEqual(os.path.basename(self.tmp.rstrip("/\\")), folders.display_name(self.tmp),
                         "an old `pathname` value still names the row by its path")

    def test_a_new_location_stores_only_that_it_is_registered(self):
        prefs, _library = _location_prefs(self, {})
        prefs.add_file_folder(self.tmp)
        self.assertEqual({"registered": True}, locations_mod.record(prefs, self.tmp))

    def test_the_sidebar_menu_has_no_show_entry(self):
        from amaze.panel import sections
        labels = [entry.label for entry in sections.FileSection.SIDEBAR_MENU if entry.label]
        self.assertNotIn("Show", labels)
        self.assertEqual(["Add", "Locate", "Rename", "Remove", "Sort by name", "Label"],
                         [label for label in labels if "Undo" not in label])


class FileSectionScanAndRerenderPinsTest(unittest.TestCase):
    """Sidebar counts, hidden-directory pruning, the section toggle, and rerender progress."""

    def test_sidebar_count_agrees_with_the_grid(self):
        """The sidebar counts no subdirectories, as the grid lists none: 3 files and 2 folders read 3."""
        tmp = tempfile.mkdtemp(prefix="amaze_count_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("a.png", "b.txt", "c.obj"):
            with open(os.path.join(tmp, name), "w") as handle:
                handle.write("x")
        os.makedirs(os.path.join(tmp, "sub_one"))
        os.makedirs(os.path.join(tmp, "sub_two"))
        prefs = _Prefs([tmp])
        folders_model = file_library.FileFolders(prefs)
        count = _wait_for_counts(folders_model)[1]
        self.assertEqual(3, count,
                         "the sidebar counts entries the grid never "
                         "shows (subdirectories)")

    def test_a_hidden_folder_is_no_sidebar_row(self):
        tmp = tempfile.mkdtemp(prefix="amaze_hidden_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "real.txt"), "w") as handle:
            handle.write("x")
        os.makedirs(os.path.join(tmp, ".git", "objects"))
        os.makedirs(os.path.join(tmp, "shown"))
        prefs = _Prefs([tmp])
        folders_model = file_library.FileFolders(prefs)
        self.assertEqual(1, _wait_for_counts(folders_model)[1], "the location's count is wrong")
        location = folders_model.index(1, 0)
        self.assertEqual(["shown"], [folders_model.index(row, 0, location).data()
                                     for row in range(folders_model.rowCount(location))],
                         "a hidden folder is listed under its location")

    def test_the_section_toggle_keeps_keys_it_does_not_know(self):
        """The Sections switches keep keys outside this registry, or an older build's tabs are lost."""
        from amaze.dialogs import prefs_window

        class _P:
            enabled_sections = ["material", "texture", "geometry",
                                "hip", "file"]

        stub = type("_Stub", (), {})()
        stub._prefs = _P()
        prefs_window.AmazePrefsState._set_section(stub, "cop", False)    # a switch applied
        self.assertEqual(["material", "file", "texture", "geometry",
                          "hip"], stub._prefs.enabled_sections,
                         "the rebuild dropped the unused keys an "
                         "older build still reads its tabs from")

    def test_rerender_counts_distinct_keys_and_registers_them(self):
        """Progress counts distinct keys; each new key goes into `_key_rows` or nothing repaints."""
        from unittest import mock
        from amaze.core import thumbnails
        prefs = _Prefs([])
        model = file_library.FileFiles(prefs)
        model._files = [("/a", "x.png"), ("/a", "x.png")]
        model._kinds = ["image", "image"]
        model._row_specs = [(None, "file", "/a/x.png"),
                            (None, "file", "/a/x.png")]
        with mock.patch.object(model, "_configure_engine_convert"), \
                mock.patch.object(
                    model, "_get_image_cache") as cache, \
                mock.patch.object(thumbnails.engine, "discard"), \
                mock.patch.object(thumbnails.engine, "request_convert"):
            cache.return_value.size = 256
            cache.return_value.invalidate = lambda full, flush=True: None    # `flush` too: rerender passes flush=False and writes the manifest once after the loop
            model.rerender_thumbnails([0, 1])
        self.assertEqual(1, model._progress_total,
                         "the total counts rows, not distinct keys - "
                         "the bar stops short and the manifest flush "
                         "that waits for it never runs")
        key = ("tex", "/a/x.png", 256)
        self.assertEqual([0, 1], model._key_rows.get(key),
                         "the rerendered key is not registered - its "
                         "result finds no row to repaint and the "
                         "generated thumbnail is never written to the disk "
                         "cache")


class _EscDuringTheFirstRender:
    """A geometry pass whose user presses Esc while the first file renders."""

    def __init__(self, *args, **kwargs):
        self.ticks = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def updateProgress(self, fraction=-1.0):
        self.ticks += 1
        if self.ticks > 1:
            raise hou.OperationInterrupted()


class GeometryThatRendersNothingIsRememberedTest(unittest.TestCase):
    """A geometry file with no picture is retried only after a change or Rerender Thumbnail."""

    def _geometry(self):
        folder = tempfile.mkdtemp(prefix="amaze_geo_none_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "rig.fbx")
        with open(path, "w") as handle:
            handle.write("no cookable geometry")
        prefs = _Prefs([folder])
        self.addCleanup(shutil.rmtree, prefs.dir, ignore_errors=True)
        model = file_library.FileFiles(prefs)
        files_actions.connect(model, file_library.FileFolders(prefs))    # its render function, as the panel passes it
        return folder, path, model

    def _rendering(self, rendered):
        from amaze.render import thumbs

        def nothing(_renderer, path, out_path, size):
            rendered.append(path)
            return False

        return mock.patch.object(
            thumbs.ThumbNailRenderer, "create_thumb_geo_file", nothing)

    def test_a_file_that_renders_nothing_is_not_rendered_again(self):
        folder, _path, model = self._geometry()
        rendered = []
        with self._rendering(rendered):
            model.set_folder(folder)
            model.set_folder(folder)
        self.assertEqual(
            1, len(rendered),
            "a geometry file that yielded no thumbnail went through the "
            "blocking render pass again on the next visit")

    def test_a_change_or_rerender_tries_again(self):
        folder, path, model = self._geometry()
        rendered = []
        with self._rendering(rendered):
            model.set_folder(folder)
            model.rerender_thumbnails([0])
            with open(path, "a") as handle:
                handle.write(" - edited")
            model.set_folder(folder)
        self.assertEqual(3, len(rendered),
                         "Rerender Thumbnail or an edited file did not "
                         "get another render")

    def test_a_file_that_renders_nothing_shows_the_missing_face_at_once(self):
        folder, _path, model = self._geometry()
        repainted = []
        model.dataChanged.connect(lambda top, _bottom, roles=(): repainted.append(top.row()))
        with self._rendering([]):
            model.set_folder(folder)
        self.assertEqual("missing", model._row_specs[0][1],
                         "a failed render left the row waiting for a render, so every paint stats the cache")
        self.assertIsNotNone(model.preview_image(0), "a failed render left the tile blank")
        self.assertIn(0, repainted, "the failed row was not repainted")

    def test_a_rendered_picture_reaches_the_cache(self):
        """The renderer writes through Houdini's own image writer, which picks the format from the name."""
        folder, path, model = self._geometry()
        from amaze.render import thumbs

        def picture(_renderer, _path, out_path, _size):
            hou.saveImageDataToFile([1.0, 0.0, 0.0, 1.0] * 4, 2, 2, out_path)
            return True

        with mock.patch.object(
                thumbs.ThumbNailRenderer, "create_thumb_geo_file", picture):
            model.set_folder(folder)
        cache = model._get_geo_cache()
        self.assertFalse(
            cache.known_failure(path),
            "a render that wrote a picture was remembered as a file with no "
            "geometry: the scratch name made Houdini write a format Qt cannot read")
        self.assertIsNotNone(cache.valid_path(path),
                             "the rendered picture was never written to the cache")

    def test_a_failure_an_older_build_recorded_is_tried_again(self):
        folder, path, model = self._geometry()
        cache = model._get_geo_cache()
        st = os.stat(path)
        cache._manifest[cache._key(path)] = {
            "mtime": st.st_mtime, "size": st.st_size, "failed": True}
        cache.save()
        rendered = []
        with self._rendering(rendered):
            model.set_folder(folder)
            model.set_folder(folder)
        self.assertEqual(
            1, len(rendered),
            "an untagged failure from the build whose scratch Qt could not "
            "read kept the file without a thumbnail, or the retry was not remembered")

    def test_an_interrupted_render_is_not_remembered(self):
        folder, _path, model = self._geometry()
        rendered = []
        with self._rendering(rendered):
            with mock.patch.object(hou, "InterruptableOperation",
                                   _EscDuringTheFirstRender):
                model.set_folder(folder)
            model.set_folder(folder)
        self.assertEqual(
            2, len(rendered),
            "an Esc during a render was remembered as a file with no "
            "geometry, so it never renders again")


class LocationColorTest(unittest.TestCase):
    """Location colours use the asset sidebars' role; the tile reads its location's colour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_loccol_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        with open(os.path.join(self.tmp, "pic.exr"), "w") as handle:
            handle.write("x")
        self.prefs = _Prefs([self.tmp])

    def test_the_sidebar_and_the_tile_return_the_locations_colour(self):
        from amaze.core import category as category_mod
        folders = file_library.FileFolders(self.prefs)
        files = file_library.FileFiles(self.prefs)
        files.set_folder(self.tmp)
        self.assertTrue(files.rowCount(), "the fixture file was not scanned")
        # Row 0 is "All" - a view, never coloured.
        self.assertFalse(folders.data(
            folders.index(0, 0), category_mod.SIDEBAR_COLOR_ROLE))
        row = folders.index(1, 0)
        index = files.index(0, 0)
        self.assertEqual("", folders.data(
            row, category_mod.SIDEBAR_COLOR_ROLE))
        self.assertEqual("", files.data(index, files.CategoryColorRole))
        self.prefs.set_file_folder_color(self.tmp, "#4af2a1")
        self.assertEqual("#4af2a1", folders.data(
            row, category_mod.SIDEBAR_COLOR_ROLE))
        self.assertEqual("#4af2a1",
                         files.data(index, files.CategoryColorRole))

    def test_the_role_number_matches_the_other_sections(self):
        """One delegate reads one role number, asserted against the literal UserRole + 8."""
        from PySide6 import QtCore as _Qt
        from amaze.core import gradient_library as grad_mod
        expected = int(_Qt.Qt.ItemDataRole.UserRole) + 8
        self.assertEqual(expected,
                         int(file_library.FileFiles.CategoryColorRole))
        self.assertEqual(expected,
                         int(grad_mod.GradientLibrary.CategoryColorRole))


class ABarePrefsLoadWritesNothingButItsOwnFile(unittest.TestCase):
    """`load()` never writes the library; library-writing migrations run from product surfaces only."""

    def test_load_leaves_the_library_untouched(self):
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        lib = tempfile.mkdtemp(prefix="amaze_bareload_lib_")
        self.addCleanup(shutil.rmtree, lib, ignore_errors=True)
        home = tempfile.mkdtemp(prefix="amaze_bareload_home_")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with open(os.path.join(home, "settings.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"directory": lib,
                       "library_user": test_support.FIXTURE_USER,
                       "material_favorites": ["mat-a"],
                       "file_folders": ["/somewhere/"]}, fh)
        p = prefs_module.Prefs()
        p.path = home
        p.load()
        self.assertEqual(
            [], os.listdir(lib),
            "a bare load() wrote the library - the write that once "
            "moved live data during a suite run")
        self.assertIn(
            "material_favorites", p.data,
            "load() removed the migration source itself - the locations "
            "functions do that, after the product requests a favourite")


class AStarIsKeptThroughRelocateFolder(unittest.TestCase):
    """Star a row, Locate the folder, re-scan: the star is keyed to the location id and stays set."""

    def test_the_star_is_still_set_at_the_new_path(self):
        old = tempfile.mkdtemp(prefix="amaze_move_")
        self.addCleanup(shutil.rmtree, old, ignore_errors=True)
        open(os.path.join(old, "wood.png"), "w").close()
        prefs = _Prefs([old])
        folders_model = file_library.FileFolders(prefs)
        files = file_library.FileFiles(prefs)
        files.set_folder(old)
        self.assertEqual(1, files.rowCount(), "premise: one file scanned")
        files.toggle_favorite(0)
        self.assertTrue(files.index(0, 0).data(files.FavoriteRole),
                        "premise: the star was set")

        new = tempfile.mkdtemp(prefix="amaze_moved_")
        self.addCleanup(shutil.rmtree, new, ignore_errors=True)
        os.rename(os.path.join(old, "wood.png"),
                  os.path.join(new, "wood.png"))
        prefs.save = lambda: None
        self.assertGreaterEqual(folders_model.relocate_folder(1, new), 0,
                                "premise: Locate succeeded")

        files.set_folder(new)
        self.assertEqual(1, files.rowCount(), "premise: the new scan sees it")
        self.assertTrue(
            files.index(0, 0).data(files.FavoriteRole),
            "the star was lost in the move - it was keyed to the "
            "path after all")


class TheUserPickerFollowsTheLibrary(unittest.TestCase):
    """Switching libraries reloads the open user picker with the new library's users."""

    def _state_on_a_second_library(self):
        """Preferences open on library A, plus a ready library B whose only user A does not have."""
        from amaze.core import users
        from amaze.dialogs import prefs_window

        first = test_support.fixture_prefs(self)
        state = prefs_window.AmazePrefsState(first, panel=None)

        second = test_support.fresh_library(self)
        moved = test_support.fixture_prefs(self)
        moved.dir = second
        moved.library_user = ""
        theirs = "Theirs"
        return state, first, second, users.create(moved, theirs), theirs

    def test_picking_a_library_lists_its_users(self):
        from amaze.core import users
        from amaze.dialogs import prefs_window
        state, first, second, uid_b, name_b = self._state_on_a_second_library()
        self.assertNotIn(uid_b, users.all_users(first),
                         "premise: both fixture libraries hold the same user")
        state.pick_library(second)
        listed = [row["value"] for row in state.userOptions]
        self.assertIn(uid_b, listed,
                      "the picker still lists the open library's users")
        self.assertEqual("", state.getPref(prefs_window.USER),
                         "a user of another library was picked without being chosen")

    def test_a_switch_applied_lists_the_new_librarys_users(self):
        """Apply opens B; the picker then lists B's users with B's user picked."""
        from amaze.dialogs import prefs_window
        state, first, second, uid_b, name_b = self._state_on_a_second_library()
        state.pick_library(second)
        test_support.pick_user(state, name_b)
        state.apply()
        self.assertEqual(0, state.changeCount, "premise: Apply opened library B")
        self.assertEqual((uid_b, [uid_b]),
                         (state.getPref(prefs_window.USER),
                          [row["value"] for row in state.userOptions[:-1]]),
                         "the picker shows the previous library's users after the switch")


class ReadinessIsCheckedOncePerGeneration(unittest.TestCase):
    """A list page reads stars per cell: the library is checked once until a location write."""

    def _isdir_calls_on_the_library(self, prefs, read):
        """How many times `read` stat'ed the library folder."""
        with mock.patch.object(locations_mod.os.path, "isdir", wraps=os.path.isdir) as isdir:
            read()
        return sum(1 for call in isdir.call_args_list if call.args[:1] == (prefs.dir,))

    def test_a_page_of_reads_checks_once_and_a_write_checks_again(self):
        prefs, _library = _location_prefs(self, {})
        self.assertTrue(locations_mod.ready(prefs), "premise: the library is not ready")

        def page():
            for _ in range(48):
                locations_mod.is_favourite(prefs, "139888336268658010")

        self.assertEqual(0, self._isdir_calls_on_the_library(prefs, page),
                         "every star read checked the library folder again")
        locations_mod.touch()
        self.assertEqual(1, self._isdir_calls_on_the_library(prefs, page),
                         "after `touch()` the library folder was not checked again exactly once")

    def test_a_library_that_appears_is_seen_after_forget(self):
        prefs, library = _location_prefs(self, {})
        here, away = library.rstrip("/\\"), library.rstrip("/\\") + "_away"
        os.rename(here, away)    # a share not mounted yet
        self.addCleanup(lambda: os.path.isdir(away) and os.rename(away, here))
        self.assertFalse(locations_mod.ready(prefs), "premise: an absent library reads as ready")
        os.rename(away, here)
        locations_mod.forget()    # what a library switch runs
        self.assertTrue(locations_mod.ready(prefs),
                        "a library that came back still reads as absent after `forget()`")


class NewFolderAndSaveScene(unittest.TestCase):
    """Both act on the folder shown, ask one name, and reject a name in use or one with a slash."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        self.folder = test_support.scratch_dir("amaze_new_")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.section = self.panel.sections["file"]
        self.files = self.panel.file_files_model
        self.files.set_folder(self.folder)
        self.refused = []
        for owner, name, value in (
                (debug, "refuse", lambda reason, **data: self.refused.append(str(reason))),
                (self.panel, "ask_category_name", lambda title, default="": self.answer)):
            patcher = mock.patch.object(owner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.answer = ""

    def _saving(self):
        saved = []
        patcher = mock.patch.object(hou.hipFile, "save", lambda path, *a, **k: saved.append(path))
        patcher.start()
        self.addCleanup(patcher.stop)
        return saved

    def test_new_folder_makes_the_folder_in_the_one_shown(self):
        self.answer = "Textures"
        self.section.menu_new_folder([], None)
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "Textures")))
        self.assertEqual([], self.refused)

    def test_a_taken_folder_name_is_refused(self):
        os.makedirs(os.path.join(self.folder, "Textures"))
        self.answer = "Textures"
        self.section.menu_new_folder([], None)
        self.assertEqual([messages.NEW_FOLDER_TAKEN % ("Textures", self.folder)], self.refused)

    def test_a_slash_in_a_name_is_refused_and_nothing_made(self):
        self.answer = "a/b"
        self.section.menu_new_folder([], None)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "a")))
        self.assertEqual([messages.NEW_NAME_HAS_A_SLASH % "a/b"], self.refused)

    def test_a_cancel_makes_nothing(self):
        self.answer = None
        before = set(os.listdir(self.folder))
        self.section.menu_new_folder([], None)
        self.assertEqual(before, set(os.listdir(self.folder)))
        self.assertEqual([], self.refused)

    def test_save_scene_saves_the_open_scene_under_the_name(self):
        saved = self._saving()
        self.answer = "shot"
        self.section.menu_save_scene([], None)
        self.assertEqual([os.path.join(self.folder, "shot" + scene_captures.scene_extension())],
                         saved)
        self.assertEqual([], self.refused)

    def test_a_taken_scene_name_is_refused_and_nothing_saved(self):
        name = "shot" + scene_captures.scene_extension()
        open(os.path.join(self.folder, name), "w").close()
        saved = self._saving()
        self.answer = "shot"
        self.section.menu_save_scene([], None)
        self.assertEqual([], saved)
        self.assertEqual([messages.SAVE_SCENE_TAKEN % (name, self.folder)], self.refused)

    def test_both_disabled_while_all_is_showing(self):
        self.files.set_all_folders()
        self.assertFalse(self.section.menu_new_enabled([], None))
        self.files.set_folder(self.folder)
        self.assertTrue(self.section.menu_new_enabled([], None))

    def test_the_extension_follows_the_licence(self):
        import types
        for category, extension in (("Commercial", ".hip"), ("Indie", ".hiplc"),
                                    ("Apprentice", ".hipnc"), ("ApprenticeHD", ".hipnc"),
                                    ("Education", ".hipnc")):
            with self.subTest(category=category):
                fake = types.SimpleNamespace(name=lambda c=category: c)
                with mock.patch.object(hou, "licenseCategory", lambda f=fake: f):
                    self.assertEqual(extension, scene_captures.scene_extension())


if __name__ == "__main__":
    unittest.main()
