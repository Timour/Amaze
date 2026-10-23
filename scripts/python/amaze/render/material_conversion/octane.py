"""Octane through the engine: MaterialX copied into Octane's builder, classic containers rebuilt."""

from __future__ import annotations

import hou

from amaze.core import debug, renderers
from amaze.helpers import wording
from amaze.render import material_converter, nodes
from amaze.render.material_conversion import engine, materialx, octane_reader

CLASSIC_CONTAINER = "octane_vopnet"
SOLARIS_CONTAINER = "octane_solaris_material_builder"    # wired at creation ▸r/octane-builder
SOLARIS_TERMINAL = "octane_material"
PLUMBING = ("subinput", "suboutput")
PASS_THROUGH = "mtlxdot"
CONDUCTOR = "mtlxconductor_bsdf"
SURELY_ADMITTED = "mtlxstandard_surface"    # refused only where the filter cannot answer
DROPPED = {    # inputs Octane has no place for when it renders MaterialX, by its own log
    "mtlxstandard_surface": ("tangent", "coat_affect_color", "coat_affect_roughness"),
    "mtlximage": ("filtertype", "framerange", "frameoffset", "frameendaction"),
}
WIRED_ONLY = {    # parameters Octane reads from a wire alone, its own default otherwise
    "mtlxstandard_surface": ("normal", "coat_normal"),
    "mtlximage": ("texcoord",),
    "mtlxnormalmap": ("normal", "tangent", "bitangent"),
}

_answers: dict = {}


def admitted(type_name: str) -> bool:
    """Whether Octane's builder keeps a child of `type_name`; True when its filter can't be asked."""
    if type_name not in _answers:
        try:
            said = hou.hscript("Octane_isMaterialBuilderChildAllowed " + type_name)[0]
        except hou.OperationFailed:
            said = ""
        _answers[type_name] = said.strip() != "0"    # fails open, as Octane's own filter does
    return _answers[type_name]


def mark(builder: hou.Node) -> None:
    """Octane's mark and Tab menu on a MaterialX builder, which Octane then reads as its own."""
    builder.setUserData(nodes.OCTANE_BUILDER_MARK, "1")
    try:
        import octane_material_builder    # Octane's own, on its plugin's script path
        octane_material_builder.refreshTabMenuMask(builder)
    except (ImportError, hou.Error) as exc:
        debug.event("octane", "tab menu not refreshed", builder=builder.path(), error=str(exc))


def find_shader(container: hou.Node):
    """The surface shader of any of Octane's three containers, or None."""
    if container.type().name() == SOLARIS_CONTAINER:
        terminal = next((c for c in container.children()
                         if c.type().name() == SOLARIS_TERMINAL), None)
        return terminal.input(0) if terminal is not None else None
    return materialx.terminal_feed(container, "surface")


def _fed_by(node: hou.Node, name: str = "in") -> tuple:
    """(node, output index) on `node`'s input `name`, or (None, 0)."""
    index = node.inputIndex(name)
    for conn in node.inputConnections():
        if conn.inputIndex() == index:
            return conn.inputNode(), conn.outputIndex()
    return None, 0


def _consumers(node: hou.Node) -> list:
    """(consumer, input index) for each wire leaving `node`; a network dot is a consumer too."""
    return [(conn.outputItem(), conn.inputIndex()) for conn in node.outputConnections()]


def _rewire(node: hou.Node, source, index: int) -> None:
    """Every wire leaving `node` fed instead from `source`'s output `index`; None cuts them."""
    for consumer, slot in _consumers(node):
        try:
            if isinstance(consumer, hou.NetworkDot):
                consumer.setInput(source, index)
            elif consumer is not None:
                consumer.setInput(slot, source, index)
        except hou.Error as exc:    # InvalidInput is a sibling ▸r/hou-errors
            debug.event("octane", "wire not carried", node=node.path(), error=str(exc))


def _metal(conductor: hou.Node, report) -> None:
    """A measured metal as a metalness-1 Standard Surface coloured by its head-on reflectance."""
    metal = conductor.parent().createNode("mtlxstandard_surface")
    metal.setName(wording.sanitize_usd_path(conductor.name()) + "_metal", unique_name=True)
    metal.setPosition(conductor.position())
    metal.parmTuple("base_color").set(tuple(
        materialx.normal_incidence_reflectance(float(n), float(k)) for n, k in zip(
            conductor.parmTuple("ior").eval(), conductor.parmTuple("extinction").eval())))
    metal.parm("base").set(conductor.parm("weight").eval())
    metal.parm("metalness").set(1.0)
    metal.parm("specular_roughness").set(conductor.parmTuple("roughness").eval()[0])
    if conductor.parm("thinfilm_thickness").eval():
        metal.parm("thin_film_thickness").set(conductor.parm("thinfilm_thickness").eval())
        metal.parm("thin_film_IOR").set(conductor.parm("thinfilm_ior").eval())
    normal, index = _fed_by(conductor, "normal")
    if normal is not None:
        metal.setInput(metal.inputIndex("normal"), normal, index)
    for name in ("weight", "ior", "extinction", "roughness", "thinfilm_thickness",
                 "thinfilm_ior", "tangent"):
        if _fed_by(conductor, name)[0] is not None:
            report.skip('"%s" feeds %s on the measured metal "%s", which the rebuilt metal '
                        "takes as a value" % (_fed_by(conductor, name)[0].name(), name,
                                              conductor.name()))
    report.approximate(
        '"%s": the measured complex index of refraction became a metalness-1 Standard '
        "Surface with its normal-incidence reflectance as base colour - Octane's builder "
        "takes no conductor BSDF" % conductor.name())
    for consumer, _slot in _consumers(conductor):
        if isinstance(consumer, hou.Node) and consumer.type().name() == "mtlxsurface":
            for name in ("edf", "opacity"):
                if _fed_by(consumer, name)[0] is not None:
                    report.skip('"%s" feeds %s on "%s", which the rebuilt metal does not carry'
                                % (_fed_by(consumer, name)[0].name(), name, consumer.name()))
            _rewire(consumer, metal, 0)
            consumer.destroy()
    conductor.destroy()


def _drop(node: hou.Node, report) -> None:
    """A child Octane's builder refuses, removed and named; what it fed keeps its own value."""
    fed = ['"%s" %s' % (consumer.name(), consumer.inputNames()[slot])
           for consumer, slot in _consumers(node) if isinstance(consumer, hou.Node)]
    report.skip('"%s" is a %s, which Octane\'s builder does not take, so it was left out%s' % (
        node.name(), node.type().name(),
        " and %s keeps its own value" % ", ".join(fed) if fed else ""))
    node.destroy()


def _alive(node: hou.Node) -> bool:
    try:
        node.path()
        return True
    except hou.ObjectWasDeleted:
        return False


def resolve(container: hou.Node, report) -> None:
    """Each child Octane's builder refuses wired through, rebuilt as a metal, or reported and removed."""
    if not admitted(SURELY_ADMITTED):
        debug.event("octane", "the builder filter cannot answer here; nothing removed",
                    container=container.path())
        return

    def of_type(*names):
        return [n for n in container.allSubChildren(recurse_in_locked_nodes=False)
                if n.type().name().split("::")[0] in names]

    for node in of_type(PASS_THROUGH):
        _rewire(node, *_fed_by(node))
        node.destroy()
    for node in of_type(CONDUCTOR):
        _metal(node, report)
    for node in container.allSubChildren(recurse_in_locked_nodes=False):
        if _alive(node) and not admitted(node.type().name()):
            _drop(node, report)


def _at_default(node: hou.Node, name: str) -> bool:
    values = node.parmTuple(name)
    return values is None or all(parm.isAtDefault() for parm in values)


def _mixes_surfaces(node: hou.Node) -> bool:
    """An mtlxmix whose inputs are surfaces, directly or through further mixes."""
    return any(upstream is not None and (
        upstream.type().name() in materialx.SHADERS + ("mtlxsurface", "mtlxsurface_unlit")
        or (upstream.type().name() == "mtlxmix" and _mixes_surfaces(upstream)))
        for upstream in node.inputs())


def report_ignored(container: hou.Node, report) -> None:
    """Each input in use that Octane ignores when it renders MaterialX, named in the report."""
    for node in container.allSubChildren(recurse_in_locked_nodes=False):
        kind = node.type().name().split("::")[0]
        if kind == "mtlxmix" and _mixes_surfaces(node):
            report.skip('"%s" mixes two surfaces, which Octane cannot render - it shows its '
                        "error colour there" % node.name())
        if kind not in DROPPED and kind not in WIRED_ONLY:
            continue
        names = node.inputNames()
        wired = {names[conn.inputIndex()] for conn in node.inputConnections()
                 if conn.inputIndex() < len(names)}
        for name in DROPPED.get(kind, ()):
            if name in wired or not _at_default(node, name):
                report.skip('"%s" uses %s, which Octane has no place for, so it renders '
                            "without it" % (node.name(), name))
        for name in WIRED_ONLY.get(kind, ()):
            if name not in wired and not _at_default(node, name):
                report.skip('"%s" sets %s by value, which Octane reads only from a wire, so '
                            "it uses its own default" % (node.name(), name))


def classic_into(parent: hou.Node, vopnet: hou.Node, name: str = "") -> hou.Node:
    """A classic `octane_vopnet` rebuilt inside `parent` into the container a LOP renders."""
    builder = parent.createNode(SOLARIS_CONTAINER, name or vopnet.name())
    terminal = next(c for c in builder.children()
                    if c.type().name() == SOLARIS_TERMINAL)
    stock = [c for c in builder.children()
             if c != terminal and c.type().name() not in PLUMBING]
    items = [item for item in vopnet.allItems()    # dots too, or wires through them break
             if not (isinstance(item, hou.Node)
                     and item.type().name() in PLUMBING)]
    copies = dict(zip((item.path() for item in items), builder.copyItems(items)))
    out = next((c for c in vopnet.children() if c.type().name() == "suboutput"), None)
    surface = next((c for c in (out.inputConnections() if out is not None else ())
                    if c.inputIndex() == 0), None)
    copy = copies.get(surface.inputNode().path()) if surface is not None else None
    terminal.setInput(0, copy, surface.outputIndex() if copy is not None else 0)
    for child in stock:    # last: never leave the terminal wired to a deleted node
        child.destroy()
    return builder


def upgrade_to_solaris_builder(container: hou.Node) -> hou.Node:
    """A classic container rebuilt beside itself as the Solaris one, which takes its name."""
    if container.type().name() != CLASSIC_CONTAINER:
        return container
    name = container.name()
    fresh = classic_into(container.parent(), container, name + "_usd")
    try:    # its look and stamps come along: the row's colour and id ride the container
        fresh.setColor(container.color())
        fresh.setPosition(container.position())
        for key, value in container.userDataDict().items():
            fresh.setUserData(key, value)
    except hou.Error as exc:
        debug.event("octane", "container look not carried", error=str(exc))
    container.destroy()
    fresh.setName(name, unique_name=True)
    return fresh


class OctaneAPI(engine.RendererAPI):
    """Writes by copying MaterialX into Octane's builder, which renders MaterialX itself."""

    name = renderers.OCTANE.key

    def available(self) -> bool:
        return material_converter._octane_type_available()

    def build(self, parent, name, produce):
        made = nodes.build_karma_material(parent, name, produce)
        mark(made.builder)
        return made

    def to_materialx(self, container, builder, report):
        return octane_reader.to_materialx(find_shader(container), builder, report)

    def from_materialx(self, container, parent, name, report):
        copy = hou.copyNodesTo((container,), parent)[0]
        copy.setName(wording.sanitize_usd_path(name) or "material", unique_name=True)
        resolve(copy, report)
        report_ignored(copy, report)
        mark(copy)
        shader = materialx.terminal_feed(copy) or materialx.find_shader(copy)
        if shader is None:
            report.skip("no MaterialX surface shader found inside the saved network")
        return engine.Converted(copy, shader, nodes.surface_terminal_wired(copy), report)

    def for_solaris(self, container):
        return upgrade_to_solaris_builder(container)


API = OctaneAPI()
