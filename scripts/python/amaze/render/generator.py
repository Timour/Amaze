"""The Generator Engine: materials from FACTS.

A generation is a SPEC - a plain dict of named float/color values -
turned into a material through the Material Engine's one funnel
(build_karma_material + an adapter). The spec IS the interface: a
parametric UI, a rule system or a learned model only needs to produce
the same dict.

**Where the numbers come from.** The online VALUES sources publish
real measurements, shipped with Amaze as tables (res/*.json, written
by tests/harvest_online.py):

  * **PhysicallyBased** (86, CC0) - reference constants: real copper,
    real gold, water's 1.333 IOR, skin's scattering radii. Its metals
    are idealised (roughness 0): a spectral identity, not a surface.
  * **RGL / EPFL** (62, CC0) - measured materials: real surface
    roughness for brushed aluminium, copper sheet, felt, silk, paper.

They are complementary, which is exactly why generation reads BOTH: a
metal takes its COLOUR from the reference set (a metal's colour is its
spectrum - hue-rotating copper produces a metal that exists nowhere)
and its FINISH from the measured set.

A material is generated IN ITS CLASS, because the classes behave
differently: metals keep their spectrum, transmissive materials keep
their IOR exactly (water is 1.333 or it is not water), scattering
materials keep their measured mean free path, and only opaque
dielectrics - where colour is pigment, and pigment is arbitrary - get
a free hue.

The one thing the measurements never mention is what an ARTIST adds on
top: clearcoat, sheen, emission. Those rates come from the authored
corpus (res/material_specs.json - 287 real materials from Houdini's
own library and the user's), so a generated material is dressed the
way authored materials are dressed: clearcoat on about a third of
them, emission on almost none.
"""

import colorsys
import json
import os
import random

import hou

_RES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "res"
)

#: Parameter distributions measured from REAL AUTHORED materials
#: (Houdini's shipped Karma corpus plus the user's converted library),
#: written by tests/extract_specs.py. Used for the authored-character
#: rates, and as the fallback corpus when the online tables are absent.
_SPECS_FILE = os.path.join(_RES_DIR, "material_specs.json")

#: The shipped online tables: (source name, file).
_ONLINE_TABLES = (
    ("PhysicallyBased", "physicallybased_materials.json"),
    ("RGL", "rgl_materials.json"),
)

#: Scene units are metres; the measured scattering radii are in
#: centimetres. Same constant, same reason as core/matx_import.
CM_TO_SCENE_UNITS = 0.01

#: RGL publishes no category, so the class comes from the material's
#: own name and the lab's description. ORDER MATTERS: "acrylic felt" is
#: a fabric, not a plastic, so Fabric is tested first.
#: ORDER MATTERS, and it is the order of DECISIVENESS, not of taste:
#: Film comes first because "satin_blue" is a TeckWrap vinyl wrapping
#: film whose own description says so - exactly the trap that made the
#: metal classifier call it a metal ("tin" inside "satin"), and a
#: Fabric-first list would have made it a fabric and given it sheen.
#: Fabric then beats Plastic so "acrylic felt" is cloth, not plastic.
_RGL_CLASSES = (
    ("Film", ("vinyl", "wrap", "wrapping", "film")),
    ("Paint", ("paint", "lacquer", "coating", "varnish", "primer")),
    ("Fabric", ("felt", "silk", "satin", "velvet", "wool", "cotton",
                "fabric", "sari", "denim", "cloth", "linen", "tweed")),
    ("Paper", ("paper", "cardboard", "card")),
    ("Leather", ("leather",)),
    ("Wood", ("wood", "veneer", "oak", "birch", "walnut")),
    ("Plastic", ("plastic", "acrylic", "pvc", "resin")),
)

#: Class labels that ask for sheen - the fabric look the measurement
#: never states. Read from RGL keywords and PhysicallyBased tags alike.
_FABRIC_WORDS = ("fabric", "cloth", "textile", "felt", "silk", "wool",
                 "cotton", "velvet", "denim", "linen")

_online_facts = None
_real_specs = None
_rates = None


def real_specs() -> list:
    """The authored spec entries, or [] when the database is absent."""
    global _real_specs
    if _real_specs is None:
        try:
            with open(_SPECS_FILE, encoding="utf-8") as handle:
                _real_specs = json.load(handle).get("entries", [])
        except (OSError, ValueError):
            _real_specs = []
    return _real_specs


def _classes_for(uid: str, entry: dict) -> list:
    """The class labels a fact carries - the source's own where it
    publishes them, keyword-derived where it does not."""
    published = entry.get("category") or entry.get("classes")
    if published:
        return [str(c) for c in published]
    words = set(
        ("%s %s" % (uid, entry.get("description") or ""))
        .lower().replace("_", " ").replace("-", " ").split()
    )
    for label, keywords in _RGL_CLASSES:
        if words & set(keywords):
            return [label]
    return ["Metal"] if entry.get("metalness") else ["Measured"]


def _normalise(source: str, uid: str, entry: dict):
    """One shipped table row -> one fact, in shader vocabulary."""
    color = entry.get("color")
    if not color or len(color) < 3:
        return None
    return {
        "source": source,
        "name": str(uid),
        "classes": _classes_for(uid, entry),
        "color": [float(c) for c in color[:3]],
        "metalness": float(entry.get("metalness") or 0.0),
        "roughness": float(entry.get("roughness") or 0.0),
        "ior": float(entry.get("ior") or 1.5),
        "specular_color": entry.get("specularColor"),
        "transmission": float(entry.get("transmission") or 0.0),
        "transmission_dispersion": entry.get("transmissionDispersion"),
        "subsurface_radius": entry.get("subsurfaceRadius"),
        "transmission_depth": entry.get("transmissionDepth"),
        "thin_film_thickness": entry.get("thinFilmThickness"),
        "thin_film_ior": entry.get("thinFilmIor"),
        "tags": [str(t).lower() for t in (entry.get("tags") or [])],
        "description": entry.get("description") or "",
    }


def online_facts() -> list:
    """Every real online material as a fact dict. [] when no table
    ships (the generator then falls back to the authored corpus)."""
    global _online_facts
    if _online_facts is not None:
        return _online_facts
    facts = []
    for source, filename in _ONLINE_TABLES:
        try:
            with open(os.path.join(_RES_DIR, filename),
                      encoding="utf-8") as handle:
                table = json.load(handle).get("materials", {})
        except (OSError, ValueError):
            continue
        for uid, entry in sorted(table.items()):
            fact = _normalise(source, uid, entry)
            if fact is not None:
                facts.append(fact)
    _online_facts = facts
    return facts


def _is_fabric(fact: dict) -> bool:
    """Cloth, however the source says it: RGL's keyword-derived class
    or PhysicallyBased's own tags (which the class vocabulary -
    Metal/Manmade/Organic/Human/Crystal/Liquid/Plastic - cannot
    express)."""
    if any(c.lower() in _FABRIC_WORDS for c in fact.get("classes", [])):
        return True
    return any(t in _FABRIC_WORDS for t in fact.get("tags", []))


def fact_kind(fact: dict) -> str:
    """Which physical class a fact generates as. The order IS the
    exclusivity: a metal is never transmissive, and a transmissive
    material's scattering is its transmission depth, not subsurface."""
    if fact["metalness"] >= 0.5:
        return "metal"
    if fact["transmission"] >= 0.5:
        return "transmissive"
    if fact["subsurface_radius"]:
        return "subsurface"
    return "opaque"


def character_rates() -> dict:
    """How often AUTHORED materials add what the measurements never
    mention, measured from the authored corpus. The fallbacks are that
    same corpus's numbers, so behaviour holds when it is absent."""
    global _rates
    if _rates is not None:
        return _rates
    defaults = {"coat": 0.334, "emission": 0.014, "sheen": 0.021,
                "coat_roughness": 0.0}
    entries = real_specs()
    if not entries:
        _rates = defaults
        return _rates
    total = float(len(entries))
    rates = {}
    for parm in ("coat", "emission", "sheen"):
        on = [e["spec"][parm] for e in entries
              if isinstance(e["spec"].get(parm), (int, float))
              and e["spec"][parm] > 0.0]
        rates[parm] = len(on) / total
    # Over the COATED materials only: taken over all 287, the median
    # is the 0.0 that every uncoated material carries, which is not
    # "what a clearcoat's roughness looks like".
    coat_rough = sorted(
        e["spec"]["coat_roughness"] for e in entries
        if isinstance(e["spec"].get("coat_roughness"), (int, float))
        and isinstance(e["spec"].get("coat"), (int, float))
        and e["spec"]["coat"] > 0.0
    )
    rates["coat_roughness"] = (
        coat_rough[len(coat_rough) // 2] if coat_rough else 0.0
    )
    _rates = rates
    return _rates


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _own_roughness(fact):
    """The fact's OWN measured roughness, or None when it published an
    idealisation. Zero is not missing data - the reference set means it
    (a perfect mirror) - but it is not a surface either, so it is
    treated as "unstated" and filled from measurements of the same
    class. `or`-style defaulting got this wrong in both directions."""
    roughness = fact.get("roughness")
    if roughness is None or roughness <= 0.0:
        return None
    if roughness >= 0.99 and fact_kind(fact) == "metal":
        # The same ceiling the borrow pool excludes: a GGX alpha of
        # exactly 1.0 is the fit giving up, not a measurement, and a
        # fully diffuse metal is not a thing. Excluded here too, or the
        # one saturated metal sample hands its own materials the
        # finish the pool refuses to lend.
        return None
    return float(roughness)


def _measured_roughness(facts, kind, rng, fallback):
    """A roughness drawn from what was MEASURED for this class. The
    reference set lists its metals as perfect mirrors (roughness 0) -
    true of the metal, useless as a surface - so a generated metal
    takes its finish from the measured set instead."""
    # Excluded at the top end: a GGX alpha of exactly 1.0 is the
    # CEILING of the NDF fit, not a measurement - it means the lobe was
    # too wide to resolve. Fine for a felt, wrong for the one brushed
    # steel sample that saturated, which would otherwise hand generated
    # metals a fully diffuse finish.
    pool = [f["roughness"] for f in facts
            if fact_kind(f) == kind and 0.0 < f["roughness"] < 0.99]
    if not pool:
        return fallback
    return _clamp(rng.choice(pool) * rng.uniform(0.75, 1.3))


def _drift(color, rng, amount=0.04):
    """A colour nudged per channel - enough to be its own material, not
    enough to stop being the measured one."""
    return [_clamp(c * rng.uniform(1.0 - amount, 1.0 + amount))
            for c in color]


def _recolour(color, rng, hue_shift=1.0):
    """Pigment: hue free (hue_shift 1.0) or bounded (a skin tone must
    stay a skin tone), saturation and value nudged."""
    hue, sat, val = colorsys.rgb_to_hsv(*[_clamp(float(c)) for c in color])
    if hue_shift >= 1.0:
        hue = rng.random()
    else:
        hue = (hue + rng.uniform(-hue_shift, hue_shift)) % 1.0
    sat = _clamp(sat * rng.uniform(0.7, 1.3))
    val = _clamp(val * rng.uniform(0.8, 1.25), 0.02, 1.0)
    return list(colorsys.hsv_to_rgb(hue, sat, val))


def spec_from_fact(fact: dict, rng=None, facts=None):
    """One real material -> one generated spec OF THE SAME CLASS.
    Returns (spec, provenance) - the provenance being the sentence that
    says what it was made from and what was varied."""
    rng = rng or random.Random()
    facts = facts if facts is not None else online_facts()
    rates = character_rates()
    kind = fact_kind(fact)
    spec = {"base": 1.0, "specular": 1.0}
    varied = []

    if kind == "metal":
        color = _drift([_clamp(c) for c in fact["color"]], rng)
        others = [f for f in facts
                  if fact_kind(f) == "metal" and f["name"] != fact["name"]]
        if others and rng.random() < 0.4:
            # Alloy-like: two measured metals interpolated stay inside
            # the gamut real metals occupy, which a free hue does not.
            other = rng.choice(others)
            t = rng.uniform(0.15, 0.5)
            # Clamped: the reference set publishes Gold as
            # [1.059, 0.773, 0.307] - faithful to the spectral data and
            # deliberately kept that way on IMPORT, but a GENERATED
            # material with a base_color above 1 quietly adds energy.
            color = [_clamp(a * (1.0 - t) + b * t)
                     for a, b in zip(color, other["color"])]
            varied.append("blended %d%% toward %s (%s)"
                          % (round(t * 100), other["name"], other["source"]))
        own = _own_roughness(fact)
        if own is not None:
            roughness = _clamp(own * rng.uniform(0.75, 1.3))
            varied.append("its own measured finish (%.3f)" % own)
        else:
            roughness = _measured_roughness(
                facts, "metal", rng, _clamp(rng.uniform(0.05, 0.35)))
            varied.append("finish from a measured metal surface "
                          "(this one is published as a perfect mirror)")
        spec.update({
            "base_color": color,
            "metalness": 1.0,
            "specular_roughness": roughness,
            # specular_IOR is inert at metalness 1 (standard_surface
            # mixes the whole dielectric specular layer out), so it is
            # deliberately not set here. What DOES matter is the EDGE
            # tint: with specular_color left white the artistic
            # conductor Fresnel has no tint at grazing angles.
            "transmission": 0.0,
        })
        if fact.get("specular_color"):
            spec["specular_color"] = [
                _clamp(float(c)) for c in fact["specular_color"][:3]
            ]
            varied.append("measured edge tint")
    elif kind == "transmissive":
        spec.update({
            # The measured IOR is this material's identity, so it is
            # copied exactly: water is 1.333, diamond 2.417.
            "base_color": _drift(fact["color"], rng, 0.08),
            "metalness": 0.0,
            "transmission": 1.0,
            "transmission_color": _drift(fact["color"], rng, 0.08),
            "specular_roughness": _clamp(rng.uniform(0.0, 0.12)),
        })
        if fact["ior"] > 1.0:
            spec["specular_IOR"] = fact["ior"]
            varied.append("IOR %.3f kept exactly" % fact["ior"])
        else:
            # Soap Bubble publishes ior 1.0: it refracts nothing, its
            # look IS the thin film. Copying 1.0 "exactly" generates an
            # invisible material.
            spec["specular_IOR"] = 1.33
            varied.append("IOR raised off 1.0 (the source is a thin "
                          "film, not a lens)")
        if fact.get("transmission_dispersion"):
            spec["transmission_dispersion"] = fact["transmission_dispersion"]
        if fact.get("transmission_depth"):
            # Beer-Lambert depth: without it the colour is a flat
            # interface tint instead of absorption through the volume.
            spec["transmission_depth"] = fact["transmission_depth"]
            varied.append("absorption depth kept")
        if fact.get("thin_film_thickness"):
            spec["thin_film_thickness"] = fact["thin_film_thickness"]
            if fact.get("thin_film_ior"):
                spec["thin_film_IOR"] = fact["thin_film_ior"]
            varied.append("measured thin film")
    elif kind == "subsurface":
        radius = [float(r) for r in fact["subsurface_radius"][:3]]
        # A scattering material's colour is bounded: skin that
        # hue-rotates freely is no longer skin.
        color = _recolour(fact["color"], rng, hue_shift=0.05)
        spec.update({
            "base_color": color,
            "metalness": 0.0,
            "subsurface": _clamp(rng.uniform(0.5, 1.0)),
            "subsurface_color": color,
            "subsurface_radius": [r * rng.uniform(0.7, 1.4) for r in radius],
            "subsurface_scale": CM_TO_SCENE_UNITS,
            "specular_roughness": _clamp(
                (_own_roughness(fact) or _measured_roughness(
                    facts, "subsurface", rng, 0.3)) * rng.uniform(0.6, 1.5)),
            "specular_IOR": fact["ior"],
        })
        varied.append("measured scattering radius kept "
                      "(centimetres, scaled to scene metres)")
    else:
        spec.update({
            "base_color": _recolour(fact["color"], rng),
            "metalness": 0.0,
            "specular_roughness": _clamp(
                (_own_roughness(fact) or _measured_roughness(
                    facts, "opaque", rng, 0.4)) * rng.uniform(0.6, 1.5)),
            "specular_IOR": fact["ior"],
            "transmission": 0.0,
        })
        varied.append(
            "hue free (pigment), roughness from %s"
            % ("its own measurement" if _own_roughness(fact) is not None
               else "a measured surface of the same class")
        )
        if _is_fabric(fact):
            # Sheen is what makes a fabric read as fabric; the
            # measurement does not mention it, so this is an inference.
            spec["sheen"] = _clamp(rng.uniform(0.3, 0.8))
            spec["sheen_roughness"] = _clamp(rng.uniform(0.2, 0.5))
            varied.append("sheen added (inferred from its fabric class)")

    # What an artist adds on top, at the rate authored materials carry
    # it. Never on a transmissive material - a clearcoat over glass is
    # a second interface nobody authors by accident.
    if kind in ("metal", "opaque") and rng.random() < rates["coat"]:
        spec["coat"] = _clamp(rng.uniform(0.5, 1.0))
        spec["coat_roughness"] = _clamp(
            rates["coat_roughness"] + rng.uniform(0.0, 0.1))
        varied.append("clearcoat (%.0f%% of authored materials have one)"
                      % (rates["coat"] * 100))
    if kind == "opaque" and rng.random() < rates["emission"]:
        spec["emission"] = _clamp(rng.uniform(0.3, 1.0))
        spec["emission_color"] = list(spec["base_color"])
        varied.append("emission (rare - %.1f%% of authored materials)"
                      % (rates["emission"] * 100))

    provenance = "Generated from %s %s (%s), as %s: %s." % (
        fact["source"], fact["name"],
        "measured" if fact["source"] == "RGL" else "reference",
        kind, "; ".join(varied),
    )
    return spec, provenance


def random_spec_with_provenance(rng=None, from_real=True):
    """(spec, provenance). The preferred source is a REAL ONLINE
    material generated in its own physical class; the authored corpus
    is the fallback when no table ships, and invented ranges the
    fallback after that (they produce materials that are plausible
    individually but uniformly distributed, which real ones are not)."""
    rng = rng or random.Random()
    if from_real:
        facts = online_facts()
        if facts:
            return spec_from_fact(rng.choice(facts), rng, facts)
        entries = real_specs()
        if entries:
            entry = rng.choice(entries)
            return (vary_spec(entry["spec"], rng),
                    "Generated from an authored material in the library "
                    "corpus (no online tables installed).")
    hue = rng.random()
    sat = rng.uniform(0.05, 0.85)
    val = rng.uniform(0.15, 0.95)
    metal = rng.random() < 0.35
    coated = rng.random() < 0.3
    transmissive = (not metal) and rng.random() < 0.12
    emissive = rng.random() < 0.08
    spec = {
        "base": rng.uniform(0.7, 1.0),
        "base_color": colorsys.hsv_to_rgb(hue, sat, val),
        "metalness": 1.0 if metal else 0.0,
        "specular": 1.0,
        "specular_roughness": rng.uniform(0.05, 0.85),
        "specular_IOR": rng.uniform(1.3, 1.8),
        "coat": rng.uniform(0.3, 1.0) if coated else 0.0,
        "coat_roughness": rng.uniform(0.0, 0.35) if coated else 0.1,
        "transmission": rng.uniform(0.5, 1.0) if transmissive else 0.0,
        "emission": rng.uniform(0.2, 1.0) if emissive else 0.0,
        "emission_color": colorsys.hsv_to_rgb(hue, sat * 0.5, 1.0),
        "sheen": rng.uniform(0.2, 0.8) if rng.random() < 0.15 else 0.0,
        "sheen_roughness": rng.uniform(0.2, 0.5),
    }
    return spec, "Generated from invented ranges (no material data found)."


def vary_spec(spec: dict, rng=None) -> dict:
    """An authored spec, varied enough to be its own material: the hue
    rotates, saturation/value and the scalar weights move within a
    fraction of their own value. Bimodal parameters (metalness, coat,
    transmission) keep their state - nudging a metal a little toward
    dielectric produces something that exists nowhere in reality.

    This is the AUTHORED-corpus path; the online path generates per
    class instead (spec_from_fact), which can keep a metal's spectrum
    because it knows the material IS a metal."""
    rng = rng or random.Random()
    out = {}
    keep_state = ("metalness", "transmission", "coat", "sheen",
                  "subsurface", "emission")
    for key, value in spec.items():
        if isinstance(value, (list, tuple)) and len(value) == 3:
            out[key] = _recolour(value, rng)
        elif isinstance(value, (int, float)):
            number = float(value)
            if key in keep_state and (number <= 0.0 or number >= 1.0):
                out[key] = number          # a state, not a dial
            elif "roughness" in key:
                out[key] = _clamp(number * rng.uniform(0.6, 1.5))
            elif key.endswith("IOR"):
                out[key] = max(1.0, number * rng.uniform(0.95, 1.05))
            else:
                out[key] = _clamp(number * rng.uniform(0.8, 1.2))
        else:
            out[key] = value
    return out


def spec_name(spec, rng=None) -> str:
    """A readable name describing the spec's dominant character."""
    rng = rng or random.Random()
    if spec.get("emission", 0) > 0:
        kind = "glow"
    elif spec.get("transmission", 0) > 0:
        kind = "glass"
    elif spec.get("metalness", 0) >= 0.5:
        kind = "metal"
    elif spec.get("subsurface", 0) > 0:
        kind = "skin"
    elif spec.get("sheen", 0) > 0:
        kind = "fabric"
    else:
        kind = "surface"
    roughness = spec.get("specular_roughness", 0)
    if roughness > 0.55:
        finish = "rough"
    elif roughness > 0.2:
        finish = "satin"
    else:
        finish = "glossy"
    if spec.get("coat", 0) > 0:
        finish = "coated_" + finish
    return "gen_%s_%s_%03d" % (finish, kind, rng.randint(0, 999))


def spec_adapter(spec):
    """Material Engine adapter: produce(builder) -> surface shader with
    the spec's values applied. The one funnel does everything else
    (container contract, output wiring, invariant check)."""

    def produce(builder):
        from amaze.core import debug

        shader = builder.createNode("mtlxstandard_surface")
        for key, value in spec.items():
            parm_tuple = shader.parmTuple(key)
            if parm_tuple is None:
                debug.event("generate", "spec key not on shader",
                            key=key, shader=shader.type().name())
                continue
            try:
                if isinstance(value, (tuple, list)):
                    parm_tuple.set(tuple(value))
                else:
                    parm = shader.parm(key)
                    if parm is not None:
                        parm.set(float(value))
            except (hou.Error, TypeError, ValueError) as exc:
                # One bad value must not cost the whole material.
                debug.event("generate", "spec value rejected",
                            key=key, error=str(exc))
        return shader

    return produce


def generate_random_material(parent: hou.Node, rng=None):
    """Build one generated material under `parent` (a matnet - use an
    /obj staging matnet, never a live materiallibrary; wiki: amaze
    retranslation model). Returns (builder, spec).

    The provenance goes on the node's COMMENT: these numbers come from
    measured CC0 datasets, and a material should still be able to say
    where it came from long after the session that made it."""
    from amaze.core import debug
    from amaze.render import nodes

    rng = rng or random.Random()
    spec, provenance = random_spec_with_provenance(rng)
    name = spec_name(spec, rng)
    builder, shader, wired = nodes.build_karma_material(
        parent, name, spec_adapter(spec)
    )
    if not wired:
        # A GENERATED material that renders black is a defect in the
        # generator, not in the user's input - so it is named against
        # the spec that produced it, which is the only thing that can
        # be used to reproduce it.
        debug.event("generate", "generated material is not wired",
                    name=name, fact_kind=spec.get("fact_kind", ""))
    if builder is not None:
        try:
            builder.setComment(provenance)
        except hou.Error as exc:
            debug.event("generate", "comment not set", error=str(exc))
    debug.event("generate", "provenance", name=name, text=provenance)
    return builder, spec
