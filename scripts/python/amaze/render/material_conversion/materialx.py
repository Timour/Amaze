"""MaterialX, the hub: its builder is the Material Engine's, and every route passes here."""

from __future__ import annotations

import hou

from amaze.render import nodes
from amaze.render.material_conversion import engine

SHADERS = ("mtlxstandard_surface", "mtlxopen_pbr_surface")


def find_shader(container: hou.Node):
    """The MaterialX surface shader inside a MaterialX material's container, or None."""
    for node in container.allSubChildren():
        if node.type().name() in SHADERS:
            return node
    return None


def find_conductor(container: hou.Node):
    """The MaterialX conductor BSDF a measured metal is built as, or None."""
    for node in container.allSubChildren():
        if node.type().name() == "mtlxconductor_bsdf":
            return node
    return None


def find_displacement(container: hou.Node):
    """The MaterialX displacement inside a container, or None."""
    for node in container.allSubChildren():
        if node.type().name() == "mtlxdisplacement":
            return node
    return None


def terminal_feed(container: hou.Node, role: str = "surface"):
    """What feeds a builder's `surface` or `displacement` terminal, either builder shape; or None."""
    children = container.children()
    for child in children:
        output, name = child.parm("connectorkind"), child.parm("parmname")
        if (child.type().name() == "subnetconnector" and output is not None
                and output.eval() == 1 and name is not None and name.eval() == role):
            return next(iter(child.inputs()), None)
    for child in children:
        if child.type().name() == "suboutput":
            inputs = child.inputs()
            index = 0 if role == "surface" else 1
            return inputs[index] if len(inputs) > index else None
    return None


def normal_incidence_reflectance(n: float, k: float) -> float:
    """A conductor's Fresnel reflectance head-on, from its complex index n + ik. ▸r/redshift-nodes"""
    return ((n - 1.0) ** 2 + k ** 2) / ((n + 1.0) ** 2 + k ** 2)


class MaterialXAPI(engine.RendererAPI):
    """The hub: the engine routes every other pair through its builder."""

    name = engine.HUB

    def available(self) -> bool:
        return True

    def build(self, parent, name, produce):
        return nodes.build_karma_material(parent, name, produce)

    def to_materialx(self, container, builder, report):
        raise TypeError("MaterialX is the hub: the engine never converts it to itself")

    def from_materialx(self, container, parent, name, report):
        raise TypeError("MaterialX is the hub: the engine never converts it to itself")


API = MaterialXAPI()
