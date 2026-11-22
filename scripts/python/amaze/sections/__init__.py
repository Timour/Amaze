"""The sections, one file each, and their registry: what the pane shows per tab. ▸o/section-api"""

from amaze.core import section_list
from amaze.sections import code, color, file, material, node

SECTION_INDEX = {cls.key: cls for cls in (    # the registry keyed for lookup; a new section is a class here and a line in section_list
    material.MaterialSection, color.GradientSection, node.CopSection, code.CodeSection,
    file.FileSection)}

SECTION_CLASSES = tuple(SECTION_INDEX[key] for key in section_list.keys())    # in tab order, which section_list holds


def save_guess(keys, nodes, prefer: str = "") -> str:
    """Which of `keys` the save dialog preselects for `nodes`. ▸p/save-section-row"""
    if prefer in keys:    # a drop onto the open section means that section
        return prefer
    return min(keys, key=lambda key: SECTION_INDEX[key].save_rank(nodes))


def build_sections(pane) -> dict:
    """Instantiate every section against a pane engine."""
    return {cls.key: cls(pane) for cls in SECTION_CLASSES}
