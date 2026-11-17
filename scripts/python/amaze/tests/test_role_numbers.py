"""The family's Qt role numbers: declared once on the class, checked by value."""

import inspect
import re
import sys
import os
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from PySide6 import QtCore

from amaze.core import code_library
from amaze.core import cop_library
from amaze.core import gradient_library
from amaze.core import library
from amaze.core import matx_library
from amaze.tests import test_support                     # noqa: F401

_USER = int(QtCore.Qt.ItemDataRole.UserRole)

FAMILY_ROLES = {
    "IdRole": _USER,                  # 256
    "CategoryRole": _USER + 1,        # 257  proxy: category (a LIST)
    "FavoriteRole": _USER + 2,        # 258  proxy: favourite
    "RendererRole": _USER + 3,        # 259  proxy: the KIND field
    "TagRole": _USER + 4,             # 260  proxy: tags
    "DateRole": _USER + 5,            # 261
    "RendererLabelRole": _USER + 6,   # 262
    "LicenceRole": _USER + 7,         # 263
    "CategoryColorRole": _USER + 8,   # 264  delegate: tile colour band
    "VersionsRole": _USER + 9,        # 265
    "NotesRole": _USER + 10,          # 266  delegate: notes badge
    "ActiveVersionRole": _USER + 11,  # 267
    "CropRole": _USER + 12,           # 268  delegate: a capture fills the tile
}

FAMILY_MODELS = (
    library.MaterialLibrary,
    cop_library.CopLibrary,
    code_library.CodeLibrary,
    gradient_library.GradientLibrary,
    matx_library.MatxOnlineLibrary,
)

FAMILY_MODULES = (
    library, cop_library, code_library, gradient_library, matx_library,
)


class TheRolesAreDeclaredOnTheClass(unittest.TestCase):
    """Roles are declared on the class, so no instance attribute hides a subclass's role."""

    def test_material_library_declares_every_family_role_on_the_class(self):
        for name, number in FAMILY_ROLES.items():
            value = getattr(library.MaterialLibrary, name, None)
            self.assertIsNotNone(
                value,
                "MaterialLibrary has no %s on the CLASS - an "
                "instance-only role hides a subclass's own" % name)
            self.assertEqual(
                int(value), number,
                "MaterialLibrary.%s is %s, the family number is %s"
                % (name, int(value), number))

    def test_every_family_model_agrees_by_number(self):
        """A model may declare a subset, but each family role it declares has the family's number."""
        for model in FAMILY_MODELS:
            for name, number in FAMILY_ROLES.items():
                value = getattr(model, name, None)
                if value is None:
                    continue
                self.assertEqual(
                    int(value), number,
                    "%s.%s is %s, the family number is %s - the proxy and "
                    "delegate read NUMBERS, so this row filters or "
                    "paints wrongly with nothing raised"
                    % (model.__name__, name, int(value), number))

    def test_a_models_own_roles_stay_off_the_family_numbers(self):
        """A section's private role must not use a family number."""
        family_numbers = set(FAMILY_ROLES.values())
        for model in FAMILY_MODELS:
            for name in dir(model):
                if not name.endswith("Role") or name in FAMILY_ROLES:
                    continue
                value = getattr(model, name)
                if not isinstance(value, int) and not hasattr(value, "__int__"):
                    continue
                self.assertNotIn(
                    int(value), family_numbers,
                    "%s.%s reuses family number %s"
                    % (model.__name__, name, int(value)))

    def test_no_family_module_assigns_a_role_on_the_instance(self):
        """An instance role assignment in any family module fails: it would hide a subclass's role."""
        pattern = re.compile(r"self\.\w*Role\s*=[^=]")
        for module in FAMILY_MODULES:
            source = inspect.getsource(module)
            hits = sorted(set(pattern.findall(source)))
            self.assertFalse(
                hits,
                "%s assigns roles on the instance (%s) - declare them "
                "as CLASS attributes, or a subclass's declarations are "
                "silently shadowed by the base's __init__"
                % (module.__name__, ", ".join(h.strip() for h in hits)))


if __name__ == "__main__":
    unittest.main()
