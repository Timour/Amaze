"""The family's Qt role NUMBERS are one declaration, read off the CLASS. The shared proxy matches on hard-coded numbers and silently ignores a filter on any other role, and an instance attribute assigned in `__init__` shadows a subclass's class attribute - which is how two role tables agree today and drift later. Qt reserves nothing above UserRole, so the agreement is ours to hold. Six of these numbers are load-bearing LITERALS elsewhere, which is why the table pins values rather than only cross-model equality. ▸archive/test_role_numbers.py"""

import inspect
import re
import sys
import os
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from PySide6 import QtCore                               # noqa: E402

from amaze.core import code_library                      # noqa: E402
from amaze.core import cop_library                       # noqa: E402
from amaze.core import gradient_library                  # noqa: E402
from amaze.core import library                           # noqa: E402
from amaze.core import matx_library                      # noqa: E402

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


class TheRolesLiveOnTheClass(unittest.TestCase):
    """Reading a role off the CLASS is the anti-shadowing contract - an inherited class attribute has no instance write left to shadow it."""

    def test_the_engine_declares_every_family_role_on_the_class(self):
        for name, number in FAMILY_ROLES.items():
            value = getattr(library.MaterialLibrary, name, None)
            self.assertIsNotNone(
                value,
                "MaterialLibrary does not answer %s on the CLASS - an "
                "instance-only role is one a subclass shadows" % name)
            self.assertEqual(
                int(value), number,
                "MaterialLibrary.%s is %s, the family says %s"
                % (name, int(value), number))

    def test_every_family_model_agrees_by_number(self):
        """A model may declare a SUBSET, but every family name it does answer must carry the family's number."""
        for model in FAMILY_MODELS:
            for name, number in FAMILY_ROLES.items():
                value = getattr(model, name, None)
                if value is None:
                    continue
                self.assertEqual(
                    int(value), number,
                    "%s.%s is %s, the family says %s - the proxy and "
                    "delegate read NUMBERS, so this row filters or "
                    "paints wrongly with nothing raised"
                    % (model.__name__, name, int(value), number))

    def test_a_models_own_roles_stay_off_the_family_numbers(self):
        """A section's private role must not sit on a family number, or asking a palette for its favourite answers its colours."""
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
        """The MECHANISM, not today's values - an instance role assignment anywhere in a family module recreates the shadowing trap, so the pattern itself is refused."""
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
