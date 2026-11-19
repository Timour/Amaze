"""Every renderer Amaze offers, in menu order; a renderer is hidden, shown, renamed or added here."""
from typing import NamedTuple


class Renderer(NamedTuple):
    """One renderer; `key` is what libraries store and never changes, `label` is what people read."""

    key: str
    label: str
    engine: str
    icon: str
    converter: str
    switch: str
    switch_stored: str
    samples: str
    samples_default: int
    samples_range: tuple
    samples_tip: str
    aliases: tuple = ()
    tile_icon: str = ""    # this renderer's icon on a material's tile, an image in `ui/`
    classic_container: str = ""    # the /mat-only VOP container its plugin makes
    usd_builder: str = ""    # its LOP-capable container, which a classic one is rebuilt as
    builder_mark: str = ""    # user data marking its own builder, a plain subnet ▸r/octane-builder


KARMA = Renderer("Karma", "MaterialX", "Karma", "filter_materialx", "materialx",
                 "renderer_matx_enabled", "renderer_materialx",
                 "karma_rendersamples", 9, (1, 256), "PREFS_SAMPLES_KARMA",
                 aliases=("MaterialX", "MtlX"), tile_icon="renderer_materialx")
REDSHIFT = Renderer("Redshift", "Redshift", "Redshift", "filter_redshift", "redshift",
                    "renderer_redshift_enabled", "renderer_redshift",
                    "rendersamples", 256, (1, 1024), "PREFS_SAMPLES_REDSHIFT",
                    tile_icon="renderer_redshift",
                    classic_container="redshift_vopnet",
                    usd_builder="rs_usd_material_builder")
OCTANE = Renderer("Octane", "Octane", "Octane", "filter_octane", "octane",
                  "renderer_octane_enabled", "renderer_octane",
                  "octane_rendersamples", 256, (1, 1024), "PREFS_SAMPLES_OCTANE",
                  tile_icon="renderer_octane",
                  classic_container="octane_vopnet",
                  usd_builder="octane_solaris_material_builder",
                  builder_mark="octane_material_builder")

ALL = (KARMA, REDSHIFT, OCTANE)
INTERMEDIATE = KARMA
RENDER_TAB = (REDSHIFT, KARMA, OCTANE)

RENDERABLE_CONTEXTS = ("SOP", "COP", "")    # node contexts whose tiles can hold a render; "" is a pre-context COP ▸p/nodes-section


def can_hold_a_render(context) -> bool:
    """Whether a Node row of this context can have a render; every Material row can."""
    return str(context or "").upper() in RENDERABLE_CONTEXTS


def get(stored):
    """The Renderer a stored value names, older spellings included; None when ALL has no match."""
    name = str(stored or "")
    for renderer in ALL:
        if any(known in name for known in (renderer.key,) + renderer.aliases):
            return renderer
    return None


def is_karma(stored) -> bool:
    return get(stored) is KARMA


def normalized(stored) -> str:
    """The key a stored value means: the older Karma spellings read as Karma."""
    name = str(stored or "")
    return KARMA.key if name in KARMA.aliases else name


def label(stored) -> str:
    """What a stored value is called on screen; an unknown value is shown as stored."""
    found = get(stored)
    return found.label if found is not None else str(stored or "")


def icon(stored) -> str:
    """The ui/ icon shown for a stored value in every menu that lists it; empty when it has none."""
    found = get(stored)
    return found.icon if found is not None else ""


def offered(prefs) -> tuple:
    """The renderers switched on in Preferences: every menu, row and switch that names one lists these."""
    return tuple(renderer for renderer in ALL if getattr(prefs, renderer.switch, False))
