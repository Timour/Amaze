"""Every renderer Amaze offers, in menu order: the one place to hide, show, rename or add one."""
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


KARMA = Renderer("Karma", "MaterialX", "Karma", "filter_materialx", "materialx",
                 "renderer_matx_enabled", "renderer_materialx",
                 "karma_rendersamples", 9, (1, 256), "PREFS_SAMPLES_KARMA",
                 aliases=("MaterialX", "MtlX"))
REDSHIFT = Renderer("Redshift", "Redshift", "Redshift", "filter_redshift", "redshift",
                    "renderer_redshift_enabled", "renderer_redshift",
                    "rendersamples", 256, (1, 1024), "PREFS_SAMPLES_REDSHIFT")
OCTANE = Renderer("Octane", "Octane", "Octane", "filter_octane", "octane",
                  "renderer_octane_enabled", "renderer_octane",
                  "octane_rendersamples", 256, (1, 1024), "PREFS_SAMPLES_OCTANE")

ALL = (KARMA, REDSHIFT, OCTANE)
HUB = KARMA
RENDER_TAB = (REDSHIFT, KARMA, OCTANE)


def get(stored):
    """The Renderer a stored value names, older spellings included; None for one Amaze lacks."""
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
    """What a stored value is called on screen; one Amaze does not know reads as stored."""
    found = get(stored)
    return found.label if found is not None else str(stored or "")


def icon(stored) -> str:
    """The ui/ icon a stored value wears in every menu that lists it; "" for one without."""
    found = get(stored)
    return found.icon if found is not None else ""


def offered(prefs) -> tuple:
    """The renderers Preferences leaves on: every menu, row and switch that names one lists these."""
    return tuple(renderer for renderer in ALL if getattr(prefs, renderer.switch, False))
