"""Generated materials: a spec dict built in class from measured materials ▸r/generator-facts"""

import colorsys
import functools
import json
import os
import random

import hou

import amaze
from amaze.core import material

_RES_DIR = amaze.package_file("res")

_SPECS_FILE = os.path.join(_RES_DIR, "material_specs.json")    # specs of authored materials

_ONLINE_TABLES = (    # the shipped online tables: (source name, file)
    ("PhysicallyBased", "physicallybased_materials.json"),
    ("RGL", "rgl_materials.json"),
)

_RGL_CLASSES = (    # keyword classes for RGL, first match wins, so order matters ▸r/generator-facts
    ("Film", ("vinyl", "wrap", "wrapping", "film")),
    ("Paint", ("paint", "lacquer", "coating", "varnish", "primer")),
    ("Fabric", ("felt", "silk", "satin", "velvet", "wool", "cotton",
                "fabric", "sari", "denim", "cloth", "linen", "tweed")),
    ("Paper", ("paper", "cardboard", "card")),
    ("Leather", ("leather",)),
    ("Wood", ("wood", "veneer", "oak", "birch", "walnut")),
    ("Plastic", ("plastic", "acrylic", "pvc", "resin")),
)

_FABRIC_WORDS = ("fabric", "cloth", "textile", "felt", "silk", "wool",    # classes and tags given sheen
                 "cotton", "velvet", "denim", "linen")


@functools.cache
def real_specs() -> list:
    """The authored spec entries, or [] when the database is absent."""
    try:
        with open(_SPECS_FILE, encoding="utf-8") as handle:
            return json.load(handle).get("entries", [])
    except (OSError, ValueError):
        return []


def _classes_for(uid: str, entry: dict) -> list:
    """A fact's class labels: the source's own, else derived from keywords in its name."""
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


@functools.cache
def online_facts() -> list:
    """Every shipped online material as a fact dict, cached; [] when no table ships."""
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
    return facts


def _is_fabric(fact: dict) -> bool:
    """True when a fact's classes or tags name a fabric."""
    if any(c.lower() in _FABRIC_WORDS for c in fact.get("classes", [])):
        return True
    return any(t in _FABRIC_WORDS for t in fact.get("tags", []))


def fact_kind(fact: dict) -> str:
    """The one physical class a fact generates as: metal, transmissive, subsurface or opaque."""
    if fact["metalness"] >= 0.5:
        return "metal"
    if fact["transmission"] >= 0.5:
        return "transmissive"
    if fact["subsurface_radius"]:
        return "subsurface"
    return "opaque"


@functools.cache
def character_rates() -> dict:
    """How often authored materials carry coat, emission and sheen; cached, with fallbacks."""
    defaults = {"coat": 0.334, "emission": 0.014, "sheen": 0.021,
                "coat_roughness": 0.0}
    entries = real_specs()
    if not entries:
        return defaults
    total = float(len(entries))
    rates = {}
    for parm in ("coat", "emission", "sheen"):
        on = [e["spec"][parm] for e in entries
              if isinstance(e["spec"].get(parm), (int, float))
              and e["spec"][parm] > 0.0]
        rates[parm] = len(on) / total
    coat_rough = sorted(    # over coated materials only
        e["spec"]["coat_roughness"] for e in entries
        if isinstance(e["spec"].get("coat_roughness"), (int, float))
        and isinstance(e["spec"].get("coat"), (int, float))
        and e["spec"]["coat"] > 0.0
    )
    rates["coat_roughness"] = (
        coat_rough[len(coat_rough) // 2] if coat_rough else 0.0
    )
    return rates


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _own_roughness(fact):
    """The fact's own measured roughness, or None for a zero or saturated one ▸r/generator-facts"""
    roughness = fact.get("roughness")
    if roughness is None or roughness <= 0.0:
        return None
    if roughness >= 0.99 and fact_kind(fact) == "metal":    # the same saturated-fit ceiling the borrow pool excludes - a fully diffuse metal is not a thing
        return None
    return float(roughness)


def _measured_roughness(facts, kind, rng, fallback):
    """A roughness drawn from the measured ones of this class, or `fallback` when there are none."""
    pool = [f["roughness"] for f in facts    # saturated fits excluded ▸r/generator-facts
            if fact_kind(f) == kind and 0.0 < f["roughness"] < 0.99]
    if not pool:
        return fallback
    return _clamp(rng.choice(pool) * rng.uniform(0.75, 1.3))


def _drift(color, rng, amount=0.04):
    """A colour nudged per channel by up to `amount` of itself."""
    return [_clamp(c * rng.uniform(1.0 - amount, 1.0 + amount))
            for c in color]


def _recolour(color, rng, hue_shift=1.0):
    """A recoloured pigment: hue free at hue_shift 1.0, else within it; saturation and value nudged."""
    hue, sat, val = colorsys.rgb_to_hsv(*[_clamp(float(c)) for c in color])
    if hue_shift >= 1.0:
        hue = rng.random()
    else:
        hue = (hue + rng.uniform(-hue_shift, hue_shift)) % 1.0
    sat = _clamp(sat * rng.uniform(0.7, 1.3))
    val = _clamp(val * rng.uniform(0.8, 1.25), 0.02, 1.0)
    return list(colorsys.hsv_to_rgb(hue, sat, val))


def spec_from_fact(fact: dict, rng=None, facts=None):
    """One fact as a generated spec of its own class: (spec, provenance) ▸r/generator-facts"""
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
        if others and rng.random() < 0.4:    # alloy-like: blended toward another measured metal
            other = rng.choice(others)
            t = rng.uniform(0.15, 0.5)
            color = [_clamp(a * (1.0 - t) + b * t)    # clamped: a base_color above 1 adds energy
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
            "transmission": 0.0,    # no specular_IOR: inert at metalness 1 ▸r/generator-facts
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
            spec["specular_IOR"] = 1.33    # an IOR of 1.0 would make an invisible material
            varied.append("IOR raised off 1.0 (the source is a thin "
                          "film, not a lens)")
        if fact.get("transmission_dispersion"):
            spec["transmission_dispersion"] = fact["transmission_dispersion"]
        if fact.get("transmission_depth"):
            spec["transmission_depth"] = fact["transmission_depth"]    # absorption through the volume
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
            "subsurface_scale": material.CM_TO_SCENE_UNITS,
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
            spec["sheen"] = _clamp(rng.uniform(0.3, 0.8))    # inferred from the fabric class

            spec["sheen_roughness"] = _clamp(rng.uniform(0.2, 0.5))
            varied.append("sheen added (inferred from its fabric class)")

    if kind in ("metal", "opaque") and rng.random() < rates["coat"]:    # at the authored rate
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
    """(spec, provenance) from an online fact, else the authored corpus, else invented ranges."""
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
    """An authored spec varied into a new one; on/off weights such as metalness keep their state."""
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
    """The Material Engine adapter: produce(builder) makes a surface shader with the spec applied."""

    def produce(builder):
        from amaze.render import nodes

        shader = builder.createNode("mtlxstandard_surface")
        for key, value in spec.items():
            nodes.set_shader_value(shader, key, value, "generate")
        return shader

    return produce


def generate_random_material(parent: hou.Node, rng=None):
    """One generated material under a staging matnet `parent`: (builder, spec), provenance on it."""
    from amaze.core import debug
    from amaze.render import nodes

    rng = rng or random.Random()
    spec, provenance = random_spec_with_provenance(rng)
    name = spec_name(spec, rng)
    builder, shader, wired = nodes.build_karma_material(
        parent, name, spec_adapter(spec)
    )
    if not wired:
        debug.event("generate", "generated material is not wired",    # the whole spec reproduces it
                    name=name, spec=dict(spec))
    try:
        builder.setComment(provenance)
    except hou.Error as exc:
        debug.event("generate", "comment not set", error=str(exc))
    debug.event("generate", "provenance", name=name, text=provenance)
    return builder, spec
