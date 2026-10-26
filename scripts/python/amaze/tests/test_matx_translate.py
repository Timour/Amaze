"""The `.mtlx` to VOP translator and what flattening must not lose. A MaterialX node name is scoped to its NODEGRAPH, so two graphs may each hold an `image1` - keyed by the bare name the last wins, both outputs resolve to it, and one texture is silently orphaned. ▸archive/test_matx_translate.py
"""

import functools
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.actions import materials as material_actions  # noqa: E402
from amaze.core import matx_translate  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


TWO_GRAPHS = """<?xml version="1.0"?>
<materialx version="1.39">
  <nodegraph name="graph_a">
    <image name="image1" type="color3">
      <input name="file" type="filename" value="a_diffuse.png"/>
    </image>
    <output name="out" type="color3" nodename="image1"/>
  </nodegraph>
  <nodegraph name="graph_b">
    <image name="image1" type="color3">
      <input name="file" type="filename" value="b_specular.png"/>
    </image>
    <output name="out" type="color3" nodename="image1"/>
  </nodegraph>
  <standard_surface name="surface1" type="surfaceshader">
    <input name="base_color" type="color3"
           nodegraph="graph_a" output="out"/>
    <input name="specular_color" type="color3"
           nodegraph="graph_b" output="out"/>
  </standard_surface>
  <surfacematerial name="material1" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="surface1"/>
  </surfacematerial>
</materialx>
"""


TINTED = """<?xml version="1.0"?>
<materialx version="1.38">
  <nodegraph name="graph">
    <image name="albedo" type="color3">
      <input name="file" type="filename" value="albedo.png"/>
    </image>
    <constant name="Tint" type="color3">
      <input name="value" type="color3" value="1.0, 0.5, 0.25"/>
    </constant>
    <constant name="Flat" type="vector3">
      <input name="value" type="vector3" value="0.5, 0.5, 1.0"/>
    </constant>
    <multiply name="tinted" type="color3">
      <input name="in1" type="color3" nodename="albedo"/>
      <input name="in2" type="color3" nodename="Tint"/>
    </multiply>
    <output name="out" type="color3" nodename="tinted"/>
  </nodegraph>
  <standard_surface name="surface1" type="surfaceshader">
    <input name="base_color" type="color3" nodegraph="graph" output="out"/>
  </standard_surface>
  <surfacematerial name="material1" type="material">
    <input name="surfaceshader" type="surfaceshader" nodename="surface1"/>
  </surfacematerial>
</materialx>
"""


def _file_of(vop):
    """The texture a translated mtlximage carries, basename only."""
    for parm_name in ("file", "filename"):
        parm = vop.parm(parm_name)
        if parm is not None:
            return os.path.basename(parm.evalAsString())
    return None


class TwoNodegraphsKeepTheirOwnNodes(unittest.TestCase):
    """ROADMAP 18, red before the name-path fix and green after."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="amaze_matx_translate_")
        cls.path = os.path.join(cls.tmp, "two_graphs.mtlx")
        with open(cls.path, "w", encoding="utf-8") as handle:
            handle.write(TWO_GRAPHS)
        cls.parent = hou.node("/mat") or hou.node("/").createNode("mat")

    def setUp(self):
        self.builder = nodes.make_karma_builder(self.parent, "two_graphs")
        self.addCleanup(self.builder.destroy)
        self.shader, _disp = matx_translate.build_material(
            self.path, self.builder, "two_graphs")

    def test_each_surface_input_wires_to_its_own_graph(self):
        """Two surface inputs must not land on one node. Compared as PATHS - `hou.Node` hands back a fresh wrapper per call, so an identity check cannot fail."""
        self.assertIsNotNone(self.shader, "no surface shader was built")
        base = self.shader.input(self.shader.inputIndex("base_color"))
        spec = self.shader.input(self.shader.inputIndex("specular_color"))
        self.assertIsNotNone(base, "base_color was left unwired")
        self.assertIsNotNone(spec, "specular_color was left unwired")
        self.assertNotEqual(
            base.path(), spec.path(),
            "base_color and specular_color both wired to %s" % base.path())
        self.assertEqual(_file_of(base), "a_diffuse.png",
                         "base_color must carry graph_a's texture")
        self.assertEqual(_file_of(spec), "b_specular.png",
                         "specular_color must carry graph_b's texture")


class AColourConstantKeepsItsColour(unittest.TestCase):
    """A MaterialX `constant` of a tuple type lands in the VOP parm named for that type - `value_color3`, `value_vector3` - and the bare `value` is the float signature's. ▸r/mtlx-vop-tuple-parms"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="amaze_matx_tint_")
        cls.path = os.path.join(cls.tmp, "tinted.mtlx")
        with open(cls.path, "w", encoding="utf-8") as handle:
            handle.write(TINTED)
        cls.parent = hou.node("/mat") or hou.node("/").createNode("mat")

    def setUp(self):
        self.builder = nodes.make_karma_builder(self.parent, "tinted")
        self.addCleanup(self.builder.destroy)
        self.shader, _disp = matx_translate.build_material(
            self.path, self.builder, "tinted")

    def _constant(self, name):
        found = self.builder.node(name)
        self.assertIsNotNone(found, "the %s constant was not built" % name)
        self.assertEqual("mtlxconstant", found.type().name())
        return found

    def test_each_tuple_constant_carries_its_value(self):
        for name, signature, value, why in (
                ("Tint", "color3", (1.0, 0.5, 0.25),
                 "the tint reads black, so everything multiplied by it "
                 "does too"),
                ("Flat", "vector3", (0.5, 0.5, 1.0),
                 "a flat-normal constant of zeros bends every normal it "
                 "is mixed with")):
            with self.subTest(constant=name):
                constant = self._constant(name)
                self.assertEqual(signature, constant.parm("signature").eval())
                self.assertEqual(
                    value, constant.parmTuple("value_" + signature).eval(), why)


class ATextureReferenceStaysInsideThePackage(unittest.TestCase):
    """A `file` value comes out of a DOWNLOADED document, and this is the one place in the online path where such a string becomes a filesystem path. Nothing is overwritten, but the resolved path lands in a parm, so the material reads a file the download never fetched and then ships that path onward."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_mtlx_")
        import shutil
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _file(self, *parts):
        path = os.path.join(self.dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("png")
        return os.path.normpath(path)

    def test_a_reference_resolves_inside_the_package_only(self):
        inside = self._file("wood_diffuse.png")
        nested = self._file("textures", "map.png")
        for value, resolved in (
                ("wood_diffuse.png", inside),    # the accept path runs on every online import
                ("textures\\map.png", nested),   # a Windows package's separator
                ("/etc/hosts", ""),
                ("../../../../etc/hosts", "")):
            with self.subTest(value=value):
                self.assertEqual(
                    resolved, matx_translate._resolve_file(value, self.dir, ""),
                    "%r resolved outside the package, or not at all" % value)


class OnlyHttpsIsFetched(unittest.TestCase):
    """Every URL the online path opens comes out of a remote document, and the default opener installs a FileHandler."""

    def test_only_an_https_url_is_kept(self):
        from amaze.core import matx_sources
        url = "https://example.invalid/package.zip"
        for given, kept in (("file:///Users/someone/.ssh/id_rsa", ""),
                            ("http://example.invalid/package.zip", ""),
                            (url, url)):
            with self.subTest(url=given):
                self.assertEqual(kept, matx_sources._checked_url(given))

    def test_a_redirect_may_not_downgrade_the_scheme(self):
        """Redirects are the NORMAL path here, and the stock handler follows http and ftp whatever the original scheme was. Driven with a real request, or removing the guard errors inside urllib and reads as a broken test rather than an unguarded redirect."""
        import email.message
        import urllib.request
        from amaze.core import matx_sources

        for target, followed in (("http://example.invalid/package.zip", False),
                                 ("https://example.invalid/package.zip", True)):
            with self.subTest(target=target):
                handler = matx_sources._HttpsOnlyRedirects()
                req = urllib.request.Request("https://example.invalid/a")
                answer = handler.redirect_request(
                    req, None, 302, "Found", email.message.Message(), target)
                self.assertEqual(
                    followed, answer is not None,
                    "a 302 to %s was handled the wrong way round" % target)


class BothOnlineDestinationsRunOneSequence(unittest.TestCase):
    """Into the library or into the scene: the same fetch, staging, build and warning."""

    def setUp(self):
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.seen = []

    def _record(self):
        from amaze.core import matx_sources
        return matx_sources.MatxRecord(
            source="PhysicallyBased", uid="probe-order", title="Probe Order",
            category="Metal", kind="values", licence="CC0 1.0",
            payload={"values": {"color": [0.8, 0.2, 0.1],
                                "roughness": 0.3}})

    def _obj(self):
        return sorted(child.name() for child in hou.node("/obj").children())

    def _source(self):
        case = self

        class Source:
            name = "PhysicallyBased"

            def fetch(self, record, resolution, dest_dir, progress=None):
                case.seen.append(case._obj())
                return {"values": record.payload["values"]}
        return Source()

    def _into_library(self):
        from amaze.core import library as library_mod, matx_import
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        ok, reason = matx_import.import_record(
            self._record(), self._source(), "", model, self.prefs,
            save=functools.partial(material_actions.add_asset, model))
        self.assertTrue(ok, reason)

    def _into_scene(self):
        from amaze.core import matx_import
        destination = hou.node("/mat") or hou.node("/").createNode("mat")
        builder, reason = matx_import.build_in_scene(
            self._record(), self._source(), "", destination, self.prefs)
        self.assertIsNotNone(builder, reason)
        self.addCleanup(builder.destroy)

    def test_nothing_is_staged_in_obj_while_the_download_runs(self):
        before = self._obj()
        self._into_library()
        self._into_scene()
        self.assertEqual([before, before], self.seen,
                         "a staging network sat in /obj during a download")
        self.assertEqual(before, self._obj(), "the staging was left behind")

    def test_an_unwired_output_is_reported_in_one_sentence(self):
        from amaze.core import matx_import
        real = matx_import.nodes_mod.build_karma_material

        def unwired(parent, name, produce):
            built = real(parent, name, produce)
            return built._replace(wired=False)

        matx_import.nodes_mod.build_karma_material = unwired
        self.addCleanup(setattr, matx_import.nodes_mod,
                        "build_karma_material", real)
        with test_support.captured_log() as log:
            self._into_library()
            self._into_scene()
        said = log.matching("surface output is not wired")
        self.assertEqual(2, len(said), said)
        self.assertEqual(said[0], said[1],
                         "the two destinations word one warning two ways")


class HostedPictureImportTest(unittest.TestCase):
    """A MaterialX import of a material with an Amaze render keeps it instead of rendering."""

    def setUp(self):
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 1
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        folder = tempfile.mkdtemp(prefix="amaze_hosted_test_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.hosted = os.path.join(folder, "hosted.png")
        image = QtGui.QImage(24, 24, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#3366cc"))
        image.save(self.hosted, "PNG")

    def _record(self):
        from amaze.core import matx_sources
        return matx_sources.MatxRecord(
            source="PhysicallyBased", uid="probe-hosted", title="Probe Hosted",
            category="Metal", kind="values", licence="CC0 1.0",
            payload={"values": {"color": [0.8, 0.2, 0.1], "roughness": 0.3},
                     "preview": {"offset": 0, "size": 1, "crc": 1}})

    def _source(self):
        hosted = self.hosted

        class Source:
            name = "PhysicallyBased"

            def fetch(self, record, resolution, dest_dir, progress=None):
                return {"values": record.payload["values"]}

            def read_thumb_to(self, record, path):
                shutil.copyfile(hosted, path)
        return Source()

    def test_the_hosted_picture_is_the_thumbnail_and_nothing_renders(self):
        from amaze.core import library as library_mod, matx_import, tile_icons
        from amaze.render import thumbs
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        with mock.patch.object(thumbs.ThumbNailRenderer, "create_thumb_mtlx") as render:
            ok, reason = matx_import.import_record(
                self._record(), self._source(), "", model, self.prefs,
                save=functools.partial(material_actions.add_asset, model))
        self.assertTrue(ok, reason)
        render.assert_not_called()
        thumb = QtGui.QImage(tile_icons.thumbnail_path(self.prefs, model.assets[-1].mat_id))
        self.assertEqual((24, 24), (thumb.width(), thumb.height()),
                         "the thumbnail is not the hosted picture")
        self.assertEqual("#3366cc", thumb.pixelColor(12, 12).name())

    def test_a_redshift_import_renders_its_own(self):
        from amaze.core import matx_import
        self.assertEqual("", matx_import.hosted_picture(
            self._record(), self._source(), "Redshift"))


if __name__ == "__main__":
    unittest.main()
