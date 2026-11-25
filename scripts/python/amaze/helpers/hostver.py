"""Host capabilities: call these functions instead of comparing versions. ▸p/host-opinions"""

import hou

from amaze.helpers import hostos


class Env(object):
    """The environment an Override's conditions are tested in; pass the `scale` you will apply."""

    def __init__(self, houdini=None, macos=None, windows=None,
                 linux=None, scale=None):
        self.houdini = houdini_version() if houdini is None else houdini
        self.macos = hostos.is_macos() if macos is None else macos
        self.windows = hostos.is_windows() if windows is None else windows
        self.linux = hostos.is_linux() if linux is None else linux
        self.scale = scale

    def __repr__(self):
        return ("Env(houdini=%s, os=%s, scale=%s)"
                % (self.houdini or "unknown",
                   "macos" if self.macos else
                   "windows" if self.windows else
                   "linux" if self.linux else "unknown",
                   self.scale))


class Override(object):
    """One claim about a capability; `conditions` are (description, predicate) pairs, all must hold."""

    def __init__(self, value, conditions, evidence, priority=0):
        self.value = value
        self.conditions = conditions
        self.evidence = evidence
        self.priority = priority

    def applies_to(self, env):
        """(applied, failed_conditions), the failed conditions joined with AND."""
        failed = []
        for description, predicate in self.conditions:
            try:
                if not predicate(env):
                    failed.append(description)
            except Exception as exc:                     # noqa: BLE001
                failed.append("%s raised %s"
                              % (description, type(exc).__name__))
        if failed:
            return False, " AND ".join(failed)
        return True, None

    def describe(self):
        return " AND ".join(d for d, _p in self.conditions)


class Capability(object):
    """A base value plus the overrides that may replace it."""

    def __init__(self, base, base_evidence, overrides=()):
        self.base = base
        self.base_evidence = base_evidence
        self.overrides = tuple(overrides)

    def resolve(self, env):
        value, best = self.base, None
        for override in self.overrides:
            applied, _failed = override.applies_to(env)
            if not applied:
                continue
            if best is None or override.priority >= best.priority:
                value, best = override.value, override
        return value



def _houdini_below(build):
    return ("Houdini < %d.%d.%d" % build,
            lambda env: bool(env.houdini) and env.houdini < build)


NEW_COPS = Capability(  # whether EXR->PNG can use the new COPs (copnet) with full OCIO
    base=True,
    base_evidence=(
        "21.x and 22.x ship copnet with full OCIO, in continuous use for "
        "every EXR->PNG thumbnail conversion. This is the base because "
        "it is current and because future versions should inherit it."),
    overrides=(
        Override(
            value=False,
            conditions=(_houdini_below((21, 0, 0)),),
            evidence=(
                "20.x and below ship cop2net only, with the restricted "
                "OCIO parameters - a different node type (cop2net/"
                "rop_comp vs copnet/rop_image), different parameter "
                "names and different colour handling. UNVERIFIED here: "
                "this is the legacy branch the renderer was written "
                "against and no 20.x install has run in this project. "
                "Kept because deleting an untested fallback is itself a "
                "change to a configuration nobody can check."),
        ),
    ),
)


def houdini_version():
    """(major, minor, build), or () if hou.applicationVersion fails."""
    try:
        return tuple(int(v) for v in hou.applicationVersion()[:3])
    except Exception:                                    # noqa: BLE001
        return ()


def has_new_cops():
    """Whether this Houdini has the new COPs (copnet) with full OCIO."""
    return NEW_COPS.resolve(Env())
