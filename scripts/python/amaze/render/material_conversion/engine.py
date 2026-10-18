"""Every material conversion, routed through MaterialX, the hub. ▸p/one-engine-shared-base"""

from __future__ import annotations

import importlib
from typing import NamedTuple

import hou

from amaze.core import renderers
from amaze.helpers import helpers
from amaze.render.material_conversion.report import ConversionReport

HUB = renderers.HUB.key
API_MODULES = tuple(renderer.converter for renderer in renderers.ALL)
UNWIRED = ("the surface output is not wired, so this material renders black until "
           "it is connected by hand")


class Converted(NamedTuple):
    """One conversion's result; `wired` False means it renders black."""

    builder: object
    shader: object
    wired: bool
    report: ConversionReport


class RendererAPI:
    """The calls every renderer answers; the engine asks nothing else of one."""

    name = ""    # the renderer value records store

    def available(self) -> bool:
        """Whether this Houdini has the renderer's plugin loaded."""
        raise NotImplementedError

    def build(self, parent, name, produce):
        """This renderer's own engine: (builder, shader, wired) around `produce(builder)`."""
        raise NotImplementedError

    def to_materialx(self, container, builder, report):
        """Inside a MaterialX `builder`: (shader, displacement) for this renderer's `container`."""
        raise NotImplementedError

    def from_materialx(self, container, parent, name, report) -> Converted:
        """This renderer's material for the MaterialX `container`, built under `parent`."""
        raise NotImplementedError

    def for_solaris(self, container):
        """`container` ready for a LOP material library; a classic one is rebuilt in its place."""
        return container


_registry: dict = {}


def apis() -> dict:
    """Each renderer's API by stored name, in menu order, imported on first use."""
    if not _registry:
        for module_name in API_MODULES:
            module = importlib.import_module(
                "amaze.render.material_conversion." + module_name)
            _registry[module.API.name] = module.API
    return _registry


def targets() -> tuple:
    """The renderers a material can become, in menu order."""
    return tuple(apis())


def api(renderer):
    """The API for a stored renderer value, the MaterialX family as MaterialX; None if none."""
    return apis().get(renderers.normalized(renderer))


def has_route(source, target) -> bool:
    """Whether a `source` material has a way to `target` at all, its plugins loaded or not."""
    reading, writing = api(source), api(target)
    return reading is not None and writing is not None and reading is not writing


def why_not(source, target) -> str:
    """Why a `source` material cannot become `target` in this Houdini, or "" when it can."""
    reading, writing = api(source), api(target)
    if reading is None or writing is None:
        return "%s materials have no conversion to %s" % (
            renderers.label(source), renderers.label(target))
    if reading is writing:
        return "the material is already %s" % renderers.label(target)
    for each in (reading, writing):
        if not each.available():
            return ("%s isn't loaded in this Houdini, so the conversion "
                    "can't run" % renderers.label(each.name))
    return ""


def can_convert(source, target) -> bool:
    """Whether a `source` material can become `target` in this Houdini."""
    return not why_not(source, target)


def ready_for_solaris(container, renderer):
    """`container`, a `renderer` material, as one a LOP material library renders."""
    each = api(renderer)
    return each.for_solaris(container) if each is not None else container


def convert(container, source, target, parent, name, report=None) -> Converted:
    """`container`, a `source` material, rebuilt as `target` under `parent`, via MaterialX."""
    report = report if report is not None else ConversionReport(name)
    reason = why_not(source, target)
    if reason:
        report.skip(reason)
        return Converted(None, None, False, report)
    reading, writing, hub = api(source), api(target), apis()[HUB]
    if reading is hub:
        made = writing.from_materialx(container, parent, name, report)
    else:
        built = hub.build(parent, name, lambda builder: reading.to_materialx(
            container, builder, report))
        made = Converted(built[0], built[1], built[2], report)
        if writing is not hub and made.shader is not None:
            middle = made.builder
            made = writing.from_materialx(middle, parent, name, report)
            with hou.undos.disabler():
                middle.destroy()    # the MaterialX step is scaffolding
            if made.builder is not None:
                made.builder.setName(helpers.sanitize_usd_path(name) or "material",
                                     unique_name=True)
    if made.shader is not None and not made.wired and UNWIRED not in report.skipped:
        report.skip(UNWIRED)
    return made
