"""The host-capability engine: every question about whether this environment behaves differently lives HERE - sibling of `hostos.py`, which owns OS facts. Nothing else may compare `hou.applicationVersion()` against a number, and callers ask for the ANSWER, never the version. A capability is a BASE value plus OPINIONS, each carrying its conditions and its evidence; read ▸p/host-opinions before adding one."""

import hou

from amaze.helpers import hostos


class Env(object):
    """The environment an opinion is judged against - `scale` is passed in by the caller rather than re-derived, so the value that DECIDES is the value that gets APPLIED."""

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
    """One layer's claim about a capability - `conditions` is an ordered tuple of (description, predicate) pairs, ALL of which must hold, named rather than folded into one lambda so explain() can report which one vetoed."""

    def __init__(self, value, conditions, evidence, strength=0):
        self.value = value
        self.conditions = conditions
        self.evidence = evidence
        self.strength = strength

    def applies_to(self, env):
        """(applied, vetoed_by) - EVERY condition that failed, joined, because reporting only the first invites the reader to think fixing the named one would change the answer."""
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
        """Every opinion, whether it applied, and what vetoed it - for the debug log, so a report from a machine nobody here can reproduce arrives with its composition already resolved."""
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


OBJ_PICK_DEVICE_PIXELS = Capability(  # whether GeometryViewport.queryNodeAtPixel wants DEVICE pixels rather than the documented logical point
    base=False,
    base_evidence=(
        "The documented behaviour and what SideFX ships today: the "
        "logical bottom-left GL point. MEASURED in use on macOS "
        "22.0.393 and 22.0.394, and independently CONFIRMED ON WINDOWS "
        "under H22, where picking works in both OBJ and Stage with no "
        "opinion applied at all. Two platforms, no workaround - which "
        "is what a base should look like. Unknown and future builds "
        "compose against this rather than against a workaround. "
        "SideFX's changelog records 22.0.391 as the build that fixed "
        "retina lasso and contained picking in the new UI on macOS - "
        "documentation for a reader of this report, NOT a boundary "
        "this engine tests against."),
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


NEW_COPS = Capability(  # whether the EXR->PNG conversion can use the new COPs (copnet) with full OCIO rather than a cop2net with restricted parameters
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


def obj_pick_wants_device_pixels(device_scale):
    """Whether GeometryViewport.queryNodeAtPixel wants DEVICE pixels - the affected builds do not apply the device pixel ratio themselves, so they want the point already multiplied by it, same bottom-left GL origin either way; see OBJ_PICK_DEVICE_PIXELS for the evidence and explain_pick() for a machine's resolution."""
    return OBJ_PICK_DEVICE_PIXELS.resolve(Env(scale=device_scale))


def explain_pick(device_scale):
    """The composition, resolved and itemised, for the debug log."""
    return OBJ_PICK_DEVICE_PIXELS.explain(Env(scale=device_scale))


def has_new_cops():
    """Whether this Houdini has the new COPs (copnet) with full OCIO."""
    return NEW_COPS.resolve(Env())
