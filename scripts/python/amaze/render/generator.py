"""The Generator Engine, materials from FACTS: a generation is a SPEC - a plain dict of named float/color values - turned into a material through `build_karma_material` and an adapter, generated IN CLASS from the two shipped CC0 tables plus the authored corpus's rates. ▸r/generator-facts"""

import colorsys
import json
import os
import random

import hou

import amaze

_RES_DIR = amaze.package_file("res")

_SPECS_FILE = os.path.join(_RES_DIR, "material_specs.json")    # parameter distributions measured from REAL AUTHORED materials (written by tests/extract_specs.py) - the authored-character rates, and the fallback corpus when the online tables are absent

_ONLINE_TABLES = (    # the shipped online tables: (source name, file)
    ("PhysicallyBased", "physicallybased_materials.json"),
    ("RGL", "rgl_materials.json"),
)

CM_TO_SCENE_UNITS = 0.01    # scene units are metres, the measured scattering radii centimetres - same constant, same reason as core/matx_import

_RGL_CLASSES = (    # RGL publishes no category, so the class comes from the name and description, tested in order of DECISIVENESS: Film before Metal ("tin" inside "satin_blue", a wrapping film), Fabric before Plastic ("acrylic felt" is cloth) ▸r/generator-facts
    ("Film", ("vinyl", "wrap", "wrapping", "film")),
    ("Paint", ("paint", "lacquer", "coating", "varnish", "primer")),
    ("Fabric", ("felt", "silk", "satin", "velvet", "wool", "cotton",
                "fabric", "sari", "denim", "cloth", "linen", "tweed")),
    ("Paper", ("paper", "cardboard", "card")),
    ("Leather", ("leather",)),
    ("Wood", ("wood", "veneer", "oak", "birch", "walnut")),
    ("Plastic", ("plastic", "acrylic", "pvc", "resin")),
)

_FABRIC_WORDS = ("fabric", "cloth", "textile", "felt", "silk", "wool",    # class labels that ask for sheen - the fabric look the measurement never states; read from RGL keywords and PhysicallyBased tags alike
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
    """The class labels a fact carries - the source's own where it publishes them, keyword-derived where it does not."""
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
    """Every real online material as a fact dict; [] when no table ships, and the generator falls back to the authored corpus."""
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
    """Cloth, however the source says it: RGL's keyword-derived class or PhysicallyBased's own tags, which its class vocabulary cannot express."""
    if any(c.lower() in _FABRIC_WORDS for c in fact.get("classes", [])):
        return True
    return any(t in _FABRIC_WORDS for t in fact.get("tags", []))


def fact_kind(fact: dict) -> str:
    """Which physical class a fact generates as - the order IS the exclusivity: a metal is never transmissive, and a transmissive material's scattering is its transmission depth, not subsurface."""
    if fact["metalness"] >= 0.5:
        return "metal"
    if fact["transmission"] >= 0.5:
        return "transmissive"
    if fact["subsurface_radius"]:
        return "subsurface"
    return "opaque"


def character_rates() -> dict:
    """How often AUTHORED materials add what the measurements never mention - the fallbacks are the same corpus's numbers, so behaviour holds when it is absent."""
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
    coat_rough = sorted(    # over the COATED materials only: over all of them the median is the 0.0 every uncoated one carries, which is not what a clearcoat's roughness looks like
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
    """The fact's OWN measured roughness, or None when it published an idealisation - a zero is "unstated", not a surface, and filled from measurements of the same class. ▸r/generator-facts"""
    roughness = fact.get("roughness")
    if roughness is None or roughness <= 0.0:
        return None
    if roughness >= 0.99 and fact_kind(fact) == "metal":    # the same saturated-fit ceiling the borrow pool excludes - a fully diffuse metal is not a thing
        return None
    return float(roughness)


def _measured_roughness(facts, kind, rng, fallback):
    """A roughness drawn from what was MEASURED for this class - the reference set lists its metals as perfect mirrors, true of the metal and useless as a surface."""
    pool = [f["roughness"] for f in facts    # the 0.99 ceiling excludes the saturated NDF fit - an alpha of exactly 1.0 means the lobe was too wide to resolve, and the one brushed-steel sample that saturated would hand generated metals a fully diffuse finish ▸r/generator-facts
            if fact_kind(f) == kind and 0.0 < f["roughness"] < 0.99]
    if not pool:
        return fallback
    return _clamp(rng.choice(pool) * rng.uniform(0.75, 1.3))


def _drift(color, rng, amount=0.04):
    """A colour nudged per channel - enough to be its own material, not enough to stop being the measured one."""
    return [_clamp(c * rng.uniform(1.0 - amount, 1.0 + amount))
            for c in color]


def _recolour(color, rng, hue_shift=1.0):
    """Pigment: hue free (hue_shift 1.0) or bounded (a skin tone must stay a skin tone), saturation and value nudged."""
    hue, sat, val = colorsys.rgb_to_hsv(*[_clamp(float(c)) for c in color])
    if hue_shift >= 1.0:
        hue = rng.random()
    else:
        hue = (hue + rng.uniform(-hue_shift, hue_shift)) % 1.0
    sat = _clamp(sat * rng.uniform(0.7, 1.3))
    val = _clamp(val * rng.uniform(0.8, 1.25), 0.02, 1.0)
    return list(colorsys.hsv_to_rgb(hue, sat, val))


def spec_from_fact(fact: dict, rng=None, facts=None):
    """One real material -> one generated spec OF THE SAME CLASS; returns (spec, provenance), the provenance being the sentence saying what it was made from and what was varied. ▸r/generator-facts"""
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
        if others and rng.random() < 0.4:    # alloy-like: two measured metals interpolated stay inside the gamut real metals occupy, which a free hue does not
            other = rng.choice(others)
            t = rng.uniform(0.15, 0.5)
            color = [_clamp(a * (1.0 - t) + b * t)    # clamped: the reference set publishes above-1 spectra (Gold), kept on IMPORT - a GENERATED base_color above 1 quietly adds energy
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
            "transmission": 0.0,    # specular_IOR is deliberately not set - inert at metalness 1; the EDGE tint (specular_color below) is what matters at grazing angles ▸r/generator-facts
        })
        if fact.get("specular_color"):
            spec["specular_color"] = [
                _clamp(float(c)) for c in fact["specular_color"][:3]
            ]
            varied.append("measured edge tint")
    elif kind == "transmissive":
        spec.update({
            "base_color": _drift(fact["color"], rng, 0.08),    # the measured IOR below is this material's identity, copied exactly - water 1.333, diamond 2.417
            "metalness": 0.0,
            "transmission": 1.0,
            "transmission_color": _drift(fact["color"], rng, 0.08),
            "specular_roughness": _clamp(rng.uniform(0.0, 0.12)),
        })
        if fact["ior"] > 1.0:
            spec["specular_IOR"] = fact["ior"]
            varied.append("IOR %.3f kept exactly" % fact["ior"])
        else:
            spec["specular_IOR"] = 1.33    # a published 1.0 (Soap Bubble) refracts nothing - its look IS the thin film, and copying it exactly generates an invisible material
            varied.append("IOR raised off 1.0 (the source is a thin "
                          "film, not a lens)")
        if fact.get("transmission_dispersion"):
            spec["transmission_dispersion"] = fact["transmission_dispersion"]
        if fact.get("transmission_depth"):
            spec["transmission_depth"] = fact["transmission_depth"]    # Beer-Lambert depth: without it the colour is a flat interface tint instead of absorption through the volume
            varied.append("absorption depth kept")
        if fact.get("thin_film_thickness"):
            spec["thin_film_thickness"] = fact["thin_film_thickness"]
            if fact.get("thin_film_ior"):
                spec["thin_film_IOR"] = fact["thin_film_ior"]
            varied.append("measured thin film")
    elif kind == "subsurface":
        radius = [float(r) for r in fact["subsurface_radius"][:3]]
        color = _recolour(fact["color"], rng, hue_shift=0.05)    # a scattering material's colour is bounded: skin that hue-rotates freely is no longer skin
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
            spec["sheen"] = _clamp(rng.uniform(0.3, 0.8))    # sheen is what makes a fabric read as fabric; the measurement never mentions it, so this is an inference

            spec["sheen_roughness"] = _clamp(rng.uniform(0.2, 0.5))
            varied.append("sheen added (inferred from its fabric class)")

    if kind in ("metal", "opaque") and rng.random() < rates["coat"]:    # what an artist adds on top, at the authored rate - never on a transmissive material, where a clearcoat is a second interface nobody authors by accident
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
    """(spec, provenance): a REAL ONLINE material generated in its own class, the authored corpus when no table ships, invented ranges last - those are plausible individually but uniformly distributed, which real materials are not."""
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
    """An authored spec varied enough to be its own material - hue rotates, weights move within a fraction of themselves, and bimodal parameters keep their STATE, since a metal nudged toward dielectric exists nowhere in reality. The authored-corpus path; the online path is spec_from_fact."""
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
    """Material Engine adapter: produce(builder) -> surface shader with the spec's values applied; the one funnel does everything else (container contract, output wiring, invariant check)."""

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
    """Build one generated material under `parent` (an /obj staging matnet, never a live materiallibrary) and return (builder, spec); the provenance goes on the node's COMMENT, so a material can still say where it came from long after the session that made it."""
    from amaze.core import debug
    from amaze.render import nodes

    rng = rng or random.Random()
    spec, provenance = random_spec_with_provenance(rng)
    name = spec_name(spec, rng)
    builder, shader, wired = nodes.build_karma_material(
        parent, name, spec_adapter(spec)
    )
    if not wired:
        debug.event("generate", "generated material is not wired",    # a black render here is the GENERATOR's defect, so the whole spec is logged - it is the only thing that reproduces it
                    name=name, spec=dict(spec))
    if builder is not None:
        try:
            builder.setComment(provenance)
        except hou.Error as exc:
            debug.event("generate", "comment not set", error=str(exc))
    debug.event("generate", "provenance", name=name, text=provenance)
    return builder, spec
