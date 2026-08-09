"""The .mtlx -> VOP translator, and what flattening must not lose.

A MaterialX node name is scoped to its nodegraph, so two graphs may
each hold an `image1` (research.md > a MaterialX node name is scoped
to its nodegraph). Keyed by the bare name the last one wins, both
graph outputs resolve to it, and one texture is silently orphaned.
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import matx_translate  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


#: Two graphs, each carrying a node called `image1`.
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

    def test_both_graphs_contribute_a_distinct_image(self):
        """The FILES are asserted, not the node count: `setName`
        carries `unique_name=True`, so both nodes exist even when the
        lookup keeps one and a count alone would pass."""
        images = [child for child in self.builder.children()
                  if child.type().name().startswith("mtlximage")]
        files = sorted(f for f in (_file_of(i) for i in images) if f)
        self.assertEqual(
            files, ["a_diffuse.png", "b_specular.png"],
            "both graphs' textures must reach the builder; got %r" % (files,))

    def test_each_surface_input_wires_to_its_own_graph(self):
        """base_color and specular_color must not land on one node."""
        self.assertIsNotNone(self.shader, "no surface shader was built")
        base = self.shader.input(self.shader.inputIndex("base_color"))
        spec = self.shader.input(self.shader.inputIndex("specular_color"))
        self.assertIsNotNone(base, "base_color was left unwired")
        self.assertIsNotNone(spec, "specular_color was left unwired")
        # Paths, not objects: `hou.Node` hands back a fresh wrapper per
        # call, so `assertIsNot` cannot fail.
        self.assertNotEqual(
            base.path(), spec.path(),
            "base_color and specular_color both wired to %s" % base.path())
        self.assertEqual(_file_of(base), "a_diffuse.png",
                         "base_color must carry graph_a's texture")
        self.assertEqual(_file_of(spec), "b_specular.png",
                         "specular_color must carry graph_b's texture")


if __name__ == "__main__":
    unittest.main()
