"""Redshift through the engine: its two converters, unchanged, behind the one API."""

from __future__ import annotations

from amaze.core import renderers
from amaze.render import material_converter, nodes, redshift_converter
from amaze.render.material_conversion import engine


class RedshiftAPI(engine.RendererAPI):
    """Reads with `material_converter`, writes with `redshift_converter`."""

    name = renderers.REDSHIFT.key

    def available(self) -> bool:
        """Both containers the converters read and write can be made here."""
        return all(nodes.node_type_available(name) for name in (
            renderers.REDSHIFT.classic_container, renderers.REDSHIFT.usd_builder))

    def build(self, parent, name, produce):
        return redshift_converter.build_redshift_material(parent, name, produce)

    def to_materialx(self, container, builder, report):
        return material_converter.convert_redshift_container(container, builder, report)

    def from_materialx(self, container, parent, name, report):
        builder, shader, wired, report = redshift_converter.convert_karma_builder(
            container, parent, name, report=report)
        return engine.Converted(builder, shader, wired, report)

    def for_solaris(self, container):
        return redshift_converter.upgrade_to_usd_builder(container)


API = RedshiftAPI()
