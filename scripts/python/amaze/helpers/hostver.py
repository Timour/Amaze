"""The host-capability engine: every "does this environment behave
differently here?" question lives HERE.

Sibling of `hostos.py`, which owns OS facts. Nothing else may compare
`hou.applicationVersion()` against a number, and callers ask for the
ANSWER ("which point does the pick want?"), never the version.

A capability is a BASE value plus OPINIONS, each carrying its
conditions and its evidence. Read ▸p/host-opinions before adding one -
where the base comes from and how far an opinion may be scoped are the
two things that go wrong.
"""

import hou

from amaze.helpers import hostos


#: SideFX changelog, build 22.0.391: "Fixed issues with viewport lasso
#: picking and picking with fully contained and visible geometry options
#: enabled on macOS retina displays. Also fixed issues with viewport
#: locate highlighting on macOS retina displays. The issues appeared
#: only in the new UI."
#:
#: Documentation, NOT a boundary - see OBJ_PICK_DEVICE_PIXELS.
RETINA_PICK_FIX_CHANGELOG = (22, 0, 391)


class Env(object):
    """The environment an opinion is judged against.

    `scale` is passed in by the caller rather than re-derived, so the
    value that DECIDES is the value that gets APPLIED - two separate
    reads could disagree about a window dragged between displays of
    different densities.
    """

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


class Opinion(object):
    """One layer's claim about a capability.

    conditions is an ordered tuple of (description, predicate) pairs,
    ALL of which must hold. They are named rather than folded into one
    lambda so that explain() can report which one vetoed - the
    difference between "the workaround did not apply" and "the
    workaround did not apply because this is not macOS".
    """

    def __init__(self, value, conditions, evidence, strength=0):
        self.value = value
        self.conditions = conditions
        self.evidence = evidence
        self.strength = strength

    def applies_to(self, env):
        """(applied, vetoed_by) - EVERY condition that failed, joined.

        Reporting only the first is misleading in exactly the case that
        matters. A real record from a Windows box read "vetoed_by:
        macOS" when the display was also unscaled - two independent
        reasons, one shown - which invites the reader to think that
        fixing the named one would change the answer.
        """
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
    """A base value plus the opinions that may override it."""

    def __init__(self, base, base_evidence, opinions=()):
        self.base = base
        self.base_evidence = base_evidence
        self.opinions = tuple(opinions)

    def resolve(self, env):
        value, best = self.base, None
        for opinion in self.opinions:
            applied, _vetoed = opinion.applies_to(env)
            if not applied:
                continue
            if best is None or opinion.strength >= best.strength:
                value, best = opinion.value, opinion
        return value

    def explain(self, env):
        """Every opinion, whether it applied, and what vetoed it.

        This is the point of the whole design. It goes in the debug log
        so a report from a machine nobody here can reproduce arrives
        with its composition already resolved.
        """
        considered = []
        for opinion in self.opinions:
            applied, vetoed = opinion.applies_to(env)
            considered.append({
                "value": opinion.value,
                "when": opinion.describe(),
                "applied": applied,
                "vetoed_by": vetoed,
                "strength": opinion.strength,
            })
        return {
            "env": repr(env),
            "base": self.base,
            "resolved": self.resolve(env),
            "opinions": considered,
        }


def _houdini_below(build):
    return ("Houdini < %d.%d.%d" % build,
            lambda env: bool(env.houdini) and env.houdini < build)


_ON_MACOS = ("macOS", lambda env: bool(env.macos))
_SCALED = ("a scaled display (dpr != 1)",
           lambda env: bool(env.scale) and env.scale != 1.0)


#: Whether GeometryViewport.queryNodeAtPixel wants DEVICE pixels rather
#: than the documented logical point.
OBJ_PICK_DEVICE_PIXELS = Capability(
    base=False,
    base_evidence=(
        "The documented behaviour and what SideFX ships today: the "
        "logical bottom-left GL point. MEASURED in use on macOS "
        "22.0.393 and 22.0.394, and independently CONFIRMED ON WINDOWS "
        "under H22, where picking works in both OBJ and Stage with no "
        "opinion applied at all. Two platforms, no workaround - which "
        "is what a base should look like. Unknown and future builds "
        "compose against this rather than against a workaround."),
    opinions=(
        Opinion(
            value=True,
            conditions=(_houdini_below((22, 0, 0)), _ON_MACOS, _SCALED),
            evidence=(
                "21.0.780 MEASURED with the four-way transform probe, "
                "cursor on a sphere at window-local (292, 136) in a "
                "481x279 widget at dpr 2.0: only the two DEVICE "
                "candidates returned the node. Confirmed in use - "
                "true_local [248, 174] -> passed [496, 210] -> hit, and "
                "three drops landed on the intended object. 21.0.790 in "
                "use since, same behaviour. It is a pure SCALE, never a "
                "flip: a flip alongside it puts the pick a full viewport "
                "from the cursor, which an earlier attempt did and it "
                "looked identical to the bug it was fixing. "
                "SCOPE NOTE - the macOS condition follows SideFX's "
                "changelog wording and is UNVERIFIED on Windows and "
                "Linux, which also report scale factors (150% is the "
                "Windows default). It stays narrow because a too-wide "
                "scope breaks a working configuration while a too-narrow "
                "one merely leaves a host bug in place. To settle it: "
                "run a drag on Windows at >100% scaling under 21.x and "
                "read the transform probe - if the DEVICE candidates hit "
                "there too, widen the scope and record the measurement."),
        ),
    ),
)


#: Whether the EXR->PNG conversion can use the new COPs (copnet) with
#: full OCIO rather than a cop2net with restricted parameters.
NEW_COPS = Capability(
    base=True,
    base_evidence=(
        "21.x and 22.x ship copnet with full OCIO, in continuous use for "
        "every EXR->PNG thumbnail conversion. This is the base because "
        "it is current and because future versions should inherit it."),
    opinions=(
        Opinion(
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
    """(major, minor, build), or () if hou cannot be asked."""
    try:
        return tuple(int(v) for v in hou.applicationVersion()[:3])
    except Exception:                                    # noqa: BLE001
        return ()


def houdini_major():
    """The major version, e.g. 21. Prefer a named capability - this
    exists for logging and for the diagnostics, which legitimately
    REPORT the version rather than branch on it."""
    version = houdini_version()
    return version[0] if version else 0


def obj_pick_wants_device_pixels(device_scale):
    """Whether GeometryViewport.queryNodeAtPixel wants DEVICE pixels.

    The affected builds do not apply the device pixel ratio themselves,
    so they want the point already multiplied by it. Origin and
    convention are unchanged - the same bottom-left GL point H22 takes,
    one factor apart.

    See OBJ_PICK_DEVICE_PIXELS for the evidence, and explain_pick() for
    why a given machine resolved the way it did.
    """
    return OBJ_PICK_DEVICE_PIXELS.resolve(Env(scale=device_scale))


def explain_pick(device_scale):
    """The composition, resolved and itemised, for the debug log."""
    return OBJ_PICK_DEVICE_PIXELS.explain(Env(scale=device_scale))


def has_new_cops():
    """Whether this Houdini has the new COPs (copnet) with full OCIO."""
    return NEW_COPS.resolve(Env())
