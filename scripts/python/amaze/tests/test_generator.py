"""The Generator Engine's invariants, asserted as PROPERTIES over a large random sample: physically coherent (no transmissive metal), in range, renderable (never black), honest about where the numbers came from - the facts are shipped tables, so no network."""

import collections
import colorsys
import math
import os
import random
import shutil
import struct
import sys
import re
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(    # THREE dirnames land on python/, where amaze imports from the REPO - four landed on scripts/ and silently imported the INSTALL (▸p/checkout-not-install)
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import material, matx_sources  # noqa: E402
from amaze.render import generator, nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - import redirects the debug log

SAMPLES = 400    # enough that a 1-in-100 rule (emission) is exercised


class TestFacts(unittest.TestCase):
    """The shipped corpus the generator reads."""

    def test_both_sources_ship(self):
        facts = generator.online_facts()
        sources = collections.Counter(f["source"] for f in facts)
        self.assertGreater(sources["PhysicallyBased"], 50)
        self.assertGreater(sources["RGL"], 50)
        kinds = collections.Counter(generator.fact_kind(f) for f in facts)
        for kind in ("metal", "transmissive", "subsurface", "opaque"):
            self.assertGreater(kinds[kind], 0, "no %s facts" % kind)

    def test_metals_carry_a_measured_finish(self):
        """The reference set lists metals as perfect mirrors - the measured half is what gives a generated metal its surface, and losing it makes metals silently mirrors."""
        rough = [f["roughness"] for f in generator.online_facts()
                 if generator.fact_kind(f) == "metal" and f["roughness"] > 0]
        self.assertGreaterEqual(len(rough), 5)

    def test_classifier_rejects_the_substring_trap(self):
        """The CLASSIFIER, never a pre-classified dict that cannot fail - the tin-in-satin case, ▸r/rgl-values."""
        infer = matx_sources.RGLSource.infer_metal
        for args, metal in (
                (("satin_blue", "TeckWrap vinyl wrapping film"), False),
                (("vch_golden_yellow", "TeckWrap vinyl wrapping film"), False),
                (("aniso_brushed_aluminium_1", "Brushed aluminium sheet"), True),
                (("ilm_solo_m_68", "Blue metallic material",    # no bare conductor is dark
                  [0.022, 0.033, 0.091]), False),
                (("aniso_copper_sheet", "Smooth copper sheet",
                  [0.95, 0.63, 0.53]), True),
                (("irid_flake_paint1",    # paint is a dielectric whatever it is sprayed on
                  "Iridescent flake car paint on top of aluminium with "
                  "black primer", [0.3, 0.2, 0.4]), False)):
            with self.subTest(name=args[0]):
                self.assertEqual(metal, bool(infer(*args)))

    def test_no_negative_colour_channels(self):
        """Measurement noise around black produced negative channels, and a negative base_color is not a colour."""
        for fact in generator.online_facts():
            for channel in fact["color"]:
                self.assertGreaterEqual(channel, 0.0, fact["name"])

    def test_metal_finish_pool_excludes_saturated_fits(self):
        """A GGX alpha of exactly 1.0 is the ceiling of the fit, not a measurement - a metal must not inherit it as its finish."""
        rng = random.Random(4)
        facts = generator.online_facts()
        values = [generator._measured_roughness(facts, "metal", rng, 0.2)
                  for _ in range(200)]
        self.assertLess(max(values), 0.99)


class TestGeneratedSpecs(unittest.TestCase):
    """Properties every generated spec must hold."""

    @classmethod
    def setUpClass(cls):
        rng = random.Random(20260727)
        cls.samples = [generator.random_spec_with_provenance(rng)
                       for _ in range(SAMPLES)]

    def test_physically_exclusive_states(self):
        for spec, prov in self.samples:
            metal = spec.get("metalness", 0.0) >= 0.5
            trans = spec.get("transmission", 0.0) > 0.0
            self.assertFalse(metal and trans, "metal + transmission: " + prov)
            self.assertFalse(metal and spec.get("subsurface", 0.0) > 0.0,
                             "metal + subsurface: " + prov)
            self.assertFalse(trans and spec.get("coat", 0.0) > 0.0,
                             "clearcoat over glass: " + prov)

    def test_values_in_range(self):
        for spec, prov in self.samples:
            for key, value in spec.items():
                values = value if isinstance(value, (list, tuple)) else [value]
                for number in values:
                    self.assertGreaterEqual(number, 0.0, "%s: %s" % (key, prov))
                if key.endswith("IOR"):
                    self.assertLessEqual(spec[key], 3.0, prov)
                elif key.endswith(("roughness", "_color", "metalness",
                                   "coat", "sheen", "subsurface",
                                   "transmission", "emission", "base",
                                   "specular")):
                    for number in values:
                        self.assertLessEqual(number, 1.0,
                                             "%s: %s" % (key, prov))

    def test_never_black(self):
        """A black material renders as a hole - the one result never worth generating."""
        for spec, prov in self.samples:
            self.assertGreater(sum(spec.get("base_color", [0, 0, 0])), 0.0,
                               prov)

    def test_metals_keep_a_metal_spectrum(self):
        """A metal's colour is its reflectance spectrum - hue-rotating copper makes a metal that exists nowhere, so generated metals stay inside the measured gamut."""
        measured = [colorsys.rgb_to_hsv(*[min(1.0, c) for c in f["color"]])[1]
                    for f in generator.online_facts()
                    if generator.fact_kind(f) == "metal"]
        ceiling = max(measured) + 0.05
        for spec, prov in self.samples:
            if spec.get("metalness", 0.0) < 0.5:
                continue
            sat = colorsys.rgb_to_hsv(*spec["base_color"])[1]
            self.assertLessEqual(sat, ceiling, "oversaturated metal: " + prov)

    def test_transmissive_keeps_its_measured_ior(self):
        """Water is 1.333 or it is not water - the IOR is copied, never varied; the ONE exception is a source IOR of 1.0 (Soap Bubble), where copying exactly generates an invisible material."""
        known = {round(f["ior"], 4) for f in generator.online_facts()
                 if f["ior"] > 1.0}
        for spec, prov in self.samples:
            if spec.get("transmission", 0.0) <= 0.0:
                continue
            ior = round(spec["specular_IOR"], 4)
            self.assertGreater(ior, 1.0, "invisible material: " + prov)
            if "raised off 1.0" not in prov:
                self.assertIn(ior, known, prov)

    def test_subsurface_radius_is_a_distance_in_scene_units(self):
        """The radius is a mean free path in CENTIMETRES and reaches the shader with subsurface_scale converting it to scene metres."""
        checked = 0
        for spec, prov in self.samples:
            if spec.get("subsurface", 0.0) <= 0.0:
                continue
            checked += 1
            self.assertEqual(spec["subsurface_scale"],
                             material.CM_TO_SCENE_UNITS, prov)
            radius = spec["subsurface_radius"]
            self.assertEqual(len(radius), 3, prov)
            for channel in radius:
                self.assertGreater(channel, 0.0, prov)
        self.assertGreater(checked, 0, "no scattering material sampled")

    def test_subsurface_hue_stays_bounded(self):
        """Skin that hue-rotates freely is no longer skin."""
        rng = random.Random(99)
        facts = [f for f in generator.online_facts()
                 if generator.fact_kind(f) == "subsurface"]
        for fact in facts:
            source_hue = colorsys.rgb_to_hsv(*fact["color"])[0]
            for _ in range(20):
                spec, _p = generator.spec_from_fact(fact, rng)
                hue = colorsys.rgb_to_hsv(*spec["base_color"])[0]
                delta = min(abs(hue - source_hue), 1.0 - abs(hue - source_hue))
                self.assertLessEqual(delta, 0.06, fact["name"])

    def test_character_rates_come_from_the_authored_corpus(self):
        """Clearcoat on about a third, emission on almost none - measured rates, not invented."""
        rates = generator.character_rates()
        self.assertGreater(rates["coat"], 0.2)
        self.assertLess(rates["coat"], 0.5)
        self.assertLess(rates["emission"], 0.05)
        coated = [s for s, _ in self.samples if s.get("coat", 0.0) > 0.0]
        share = len(coated) / float(len(self.samples))    # metals and opaque dielectrics are the eligible classes, so the observed share is the rate scaled by their corpus share
        self.assertGreater(share, 0.1)
        self.assertLess(share, rates["coat"] + 0.1)

    def test_fabric_gets_sheen_and_metal_does_not(self):
        facts = generator.online_facts()
        fabric = next(f for f in facts if generator._is_fabric(f))
        spec, _p = generator.spec_from_fact(fabric, random.Random(2))
        self.assertGreater(spec.get("sheen", 0.0), 0.0, fabric["name"])
        for spec, prov in self.samples:
            if spec.get("metalness", 0.0) >= 0.5:
                self.assertEqual(spec.get("sheen", 0.0), 0.0, prov)

    def test_vinyl_film_is_not_classified_as_fabric(self):
        """The satin trap in the generator's OWN class table: a colourway name must not beat the description."""
        fact = generator._normalise("RGL", "satin_blue", {
            "color": [0.68, 0.74, 0.75], "metalness": 0.0,
            "roughness": 0.3,
            "description": "TeckWrap vinyl wrapping film (Blue Satin)",
        })
        self.assertEqual(fact["classes"], ["Film"])
        self.assertFalse(generator._is_fabric(fact))

    def test_every_spec_key_exists_on_the_shader(self):
        """A key the shader does not have is set silently into nothing."""
        staging = hou.node("/obj").createNode("matnet")
        probe = staging.createNode("mtlxstandard_surface")
        try:
            keys = {k for spec, _ in self.samples for k in spec}
            missing = [k for k in sorted(keys) if probe.parmTuple(k) is None]
            self.assertEqual(missing, [])
        finally:
            staging.destroy()

    def test_provenance_names_its_source(self):
        for spec, prov in self.samples:
            self.assertTrue(prov)
            self.assertTrue(
                "PhysicallyBased" in prov or "RGL" in prov, prov
            )


class TestGeneratedMaterials(unittest.TestCase):
    """The built material, not just the numbers."""

    def test_builds_wired_and_carries_provenance(self):
        staging = hou.node("/obj").createNode("matnet")
        try:
            for seed in range(8):
                builder, spec = generator.generate_random_material(
                    staging, random.Random(seed)
                )
                self.assertIsNotNone(builder)
                self.assertTrue(nodes.surface_terminal_wired(builder),
                                "renders black")
                self.assertTrue(builder.isMaterialFlagSet())
                self.assertTrue(builder.comment(), "no provenance recorded")
        finally:
            staging.destroy()

    def test_spec_values_land_on_the_shader(self):
        staging = hou.node("/obj").createNode("matnet")
        try:
            builder, spec = generator.generate_random_material(
                staging, random.Random(11)
            )
            shader = [n for n in builder.children()
                      if n.type().name() == "mtlxstandard_surface"][0]
            for key, value in spec.items():
                parm_tuple = shader.parmTuple(key)
                if parm_tuple is None:
                    continue
                want = value if isinstance(value, (list, tuple)) else (value,)
                for got, expected in zip(parm_tuple.eval(), want):
                    self.assertAlmostEqual(float(got), float(expected),
                                           places=4, msg=key)
        finally:
            staging.destroy()


class OneShaderSetterForEveryValueSource(unittest.TestCase):
    """The generator and the measured-values import set a shader's parms one way."""

    def setUp(self):
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)

    def _rounded(self, shader, name):
        return tuple(round(v, 4) for v in shader.parmTuple(name).eval())

    def test_a_colour_with_alpha_lands_its_first_three_channels(self):
        made = nodes.build_karma_material(
            self.staging, "alpha",
            generator.spec_adapter({"base_color": [0.1, 0.2, 0.3, 1.0]}))
        self.assertEqual((0.1, 0.2, 0.3), self._rounded(made.shader, "base_color"))

    def test_a_value_that_is_not_a_number_costs_only_itself(self):
        from amaze.core import matx_import
        builder = nodes.make_karma_builder(self.staging, "values")
        shader = matx_import._values_to_standard_surface(
            {"color": [0.1, 0.2, 0.3], "metalness": "unknown", "roughness": 0.4},
            builder)
        self.assertEqual((0.1, 0.2, 0.3), self._rounded(shader, "base_color"))
        self.assertEqual((0.4,), self._rounded(shader, "specular_roughness"))


class TestCatalogueFreshness(unittest.TestCase):
    """New materials on the sites simply APPEAR and, with no network, the shipped tables ARE the catalogue - both safe eagerly because only the catalogue worker thread calls list_materials."""

    def _sources(self):
        return [s for s in matx_sources.all_sources()
                if s.name in ("RGL", "PhysicallyBased")]

    def test_offline_falls_back_to_the_shipped_table(self):
        real_text, real_json = matx_sources.get_text, matx_sources.get_json

        def dead(*args, **kwargs):
            raise OSError("simulated: no network")

        matx_sources.get_text = dead
        matx_sources.get_json = dead
        try:
            for source in self._sources():
                source.refresh()          # drop any cached catalogue
                records = source.list_materials(limit=1000)
                self.assertGreater(len(records), 50,
                                   "%s lost its offline catalogue"
                                   % source.name)
                with_colour = [
                    r for r in records
                    if (r.payload.get("values") or {}).get("color")
                ]
                self.assertEqual(len(with_colour), len(records),
                                 "%s tiles would paint grey offline"
                                 % source.name)
        finally:
            matx_sources.get_text, matx_sources.get_json = real_text, real_json
            for source in self._sources():
                source.refresh()

    def test_a_bad_live_payload_never_replaces_the_table(self):
        """Reachable is not correct - accepting a portal's valid JSON blindly once replaced the measured set with grey tiles. ▸r/matx-source-quirks"""
        pb = [s for s in self._sources() if s.name == "PhysicallyBased"][0]
        real = matx_sources.get_json
        try:
            for payload in ([{"name": "Broken"}],
                            {"error": "rate limited"},
                            [],
                            [{"name": "x%d" % i, "color": [0.5, 0.5, 0.5]}
                             for i in range(20)]):
                matx_sources.get_json = lambda *a, **k: payload
                pb.refresh()
                records = pb.list_materials(limit=1000)
                self.assertGreater(
                    len(records), 50,
                    "a bad live payload (%r) replaced the shipped table"
                    % (payload if not isinstance(payload, list)
                       else "%d items" % len(payload)))
        finally:
            matx_sources.get_json = real
            pb.refresh()

    GOOD_PAYLOAD = [{"name": "live%d" % i, "color": [0.4, 0.4, 0.4]}    # a response _usable() should ACCEPT: name + three-channel colour per entry
                    for i in range(30)]

    def _pb(self):
        return [s for s in self._sources() if s.name == "PhysicallyBased"][0]

    def _without_the_shipped_table(self, pb):
        """Point _table_path at a file that does not exist, answering the real bound method so the caller can put it back."""
        real = pb._table_path
        missing = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "no_such_physicallybased_table.json")
        self.assertFalse(
            os.path.exists(missing),
            "the stand-in table path exists, so this test is not "
            "exercising the unreadable-table branch it was written for")
        pb._table_path = lambda: missing
        return real

    def test_a_bad_payload_is_refused_with_no_table_to_fall_back_on(self):
        """The unreadable-table re-fetch goes THROUGH the shape gate - it once assigned a portal's JSON as the catalogue and surfaced as a TypeError several calls from its cause. ▸r/matx-source-quirks"""
        pb = self._pb()
        real_json = matx_sources.get_json
        real_table = self._without_the_shipped_table(pb)
        fetches = []

        def portal(url, *a, **k):
            fetches.append(url)
            return {"error": "sign in to continue"}

        matx_sources.get_json = portal
        try:
            pb.refresh()
            with self.assertRaises(Exception) as caught:
                pb.list_materials(limit=1000)
            self.assertIsNone(
                pb._all,
                "an unusable live response became the catalogue - the "
                "shape gate was bypassed on the unreadable-table path")
            self.assertNotIsInstance(
                caught.exception, TypeError,
                "the payload reached the code that slices it, so it was "
                "accepted and only failed later: %s" % caught.exception)
            self.assertGreaterEqual(
                len(fetches), 1,
                "get_json was never called - this test is not exercising "
                "the live-response path it was written for")
        finally:
            matx_sources.get_json = real_json
            pb._table_path = real_table
            pb.refresh()

    def test_a_transient_failure_still_gets_its_second_chance(self):
        """The ACCEPT path of the same branch: a transient first failure with no table to fall back on is the case the re-fetch exists for, and gating it must not have become a refusal."""
        pb = self._pb()
        real_json = matx_sources.get_json
        real_table = self._without_the_shipped_table(pb)
        answers = [OSError("simulated: timeout"), self.GOOD_PAYLOAD]

        def flaky(*a, **k):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        matx_sources.get_json = flaky
        try:
            pb.refresh()
            try:
                records = pb.list_materials(limit=1000)
            except Exception as exc:                    # noqa: BLE001
                self.fail("a good response on the retry was refused (%s), "    # NAMED on purpose: an over-strict gate raises here, and a bare traceback says only that something threw
                          "so a transient failure with no shipped table "
                          "loses the catalogue" % exc)
            self.assertEqual(
                len(self.GOOD_PAYLOAD), len(records),
                "the retry's records did not survive to the caller")
            self.assertEqual(
                [], answers,
                "the retry never happened - this test is not exercising "
                "the second chance it was written for")
        finally:
            matx_sources.get_json = real_json
            pb._table_path = real_table
            pb.refresh()

    def test_rgl_unions_the_live_list_with_the_table(self):
        """A material the site lists and the table does not must still appear - that is what new-materials-just-show-up means."""
        rgl = [s for s in self._sources() if s.name == "RGL"][0]
        real_text = matx_sources.get_text
        matx_sources.get_text = lambda *a, **k: (
            '<a href="/media/materials/brand_new_material/">x</a>'
        )
        try:
            rgl.refresh()
            names = [r.uid for r in rgl.list_materials(limit=1000)]
            self.assertIn("brand_new_material", names,
                          "a newly published material did not appear")
            self.assertIn("acrylic_felt_green", names,
                          "the shipped table was replaced instead of "
                          "unioned")
        finally:
            matx_sources.get_text = real_text
            rgl.refresh()


def _tensor_file(path, ndf_rows, rgb=None):
    """A Mitsuba tensor_file: `rgb` per channel over a 2 x 2 grid, `ndf_rows` as its NDF table."""
    fields = [("rgb", 10, (1, 1, 3, 2, 2), rgb or [0.5] * 12),
              ("ndf", 10, (len(ndf_rows), len(ndf_rows[0])),
               [v for row in ndf_rows for v in row])]
    head = 12 + 2 + 4 + sum(2 + len(n) + 2 + 1 + 8 + 8 * len(s) for n, _t, s, _v in fields)
    out, blobs, at = bytearray(b"tensor_file\0" + bytes([1, 0])), b"", head
    out += struct.pack("<I", len(fields))
    for name, dtype, shape, numbers in fields:
        blob = struct.pack("<%df" % len(numbers), *numbers)
        out += struct.pack("<H", len(name)) + name.encode() + struct.pack("<H", len(shape))
        out += bytes([dtype]) + struct.pack("<Q", at) + struct.pack("<%dQ" % len(shape), *shape)
        blobs, at = blobs + blob, at + len(blob)
    with open(path, "wb") as handle:
        handle.write(bytes(out) + blobs)


class RGLRoughnessTest(unittest.TestCase):
    """An RGL roughness on the file's u-squared grid, as Standard Surface's square root. ▸r/rgl-values"""

    WIDE = [1.0, 0.9, 0.8, 0.6, 0.4, 0.2, 0.1, 0.05, 0.0]    # half-maximum at column 4 of 9
    NARROW = [1.0, 0.45, 0.2, 0.1, 0.05, 0.02, 0.01, 0.0, 0.0]    # half-maximum at column 1

    def _roughness(self, rows):
        folder = tempfile.mkdtemp(prefix="amaze_rgl_bsdf_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "probe_rgb.bsdf")
        _tensor_file(path, rows)
        values, _note = matx_sources.RGLSource.values_from_bsdf(path, "probe")
        return values["roughness"]

    @staticmethod
    def _alpha(column):
        return math.tan((column / 8.0) ** 2 * math.pi / 2) / 0.6436

    def test_a_half_width_reads_on_the_squared_grid_and_lands_as_its_root(self):
        self.assertAlmostEqual(math.sqrt(self._alpha(4)),
                               self._roughness([self.WIDE, self.WIDE]), places=4)

    def test_an_anisotropic_file_reads_every_direction(self):
        both = math.sqrt(math.sqrt(self._alpha(4) * self._alpha(1)))
        self.assertAlmostEqual(both, self._roughness([self.WIDE, self.NARROW]), places=4)

    PEARL = [0.2, 1.2, 0.2, 1.2,    # each channel's 2 x 2 grid; column 0 is the mirror
             0.5, 0.9, 0.5, 0.9,
             1.0, 0.4, 1.0, 0.4]    # a white on average, blue at the mirror

    def _values(self, uid, rgb):
        folder = tempfile.mkdtemp(prefix="amaze_rgl_bsdf_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "probe_rgb.bsdf")
        _tensor_file(path, [self.WIDE, self.WIDE], rgb)
        return matx_sources.RGLSource.values_from_bsdf(path, uid)[0]

    def test_a_satin_film_takes_the_colour_it_reflects_at_the_mirror(self):
        values = self._values("satin_probe", self.PEARL)
        self.assertEqual([0.2, 0.5, 1.0], values.get("specularColor"))
        self.assertEqual([0.15, 0.375, 0.75], values["color"])

    def test_anything_else_keeps_its_mean_colour(self):
        values = self._values("paper_probe", self.PEARL)
        self.assertNotIn("specularColor", values)
        self.assertEqual([0.7, 0.7, 0.7], values["color"])

    def test_a_satin_with_a_neutral_mirror_stays_white(self):
        self.assertNotIn("specularColor", self._values("satin_white", [0.7] * 12))

    def test_a_painted_satin_reaches_the_import_with_its_reflection(self):
        values = matx_sources.RGLSource()._values_for("satin_blue")
        self.assertIn("specularColor", values, "the shipped satin_blue is not painted")
        self.assertLess(values["color"][0], values["color"][2], "satin_blue is not blue")


class TestDownloadIntegrity(unittest.TestCase):
    """Anything fetched from the network is data, not truth - a cached measurement is never re-fetched, so one bad response would be permanent."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="amaze_dl_")
        self.rgl = [s for s in matx_sources.all_sources()
                    if s.name == "RGL"][0]

    def test_an_error_page_is_not_kept_as_a_measurement(self):
        import os
        record = matx_sources.MatxRecord(
            source="RGL", uid="not_a_real_material",
            title="Not A Real Material", kind="values", payload={})
        real_download = matx_sources.download

        def fake_download(url, target, on_bytes=None, **kwargs):    # THE REAL SIGNATURE - a stub that does not match the thing it stands in for fails the day the real call grows an argument
            with open(target, "wb") as handle:
                handle.write(b"<html>404 Not Found</html>")

        matx_sources.download = fake_download
        try:
            with self.assertRaises(ValueError):
                self.rgl.fetch(record, None, self.tmp)
            self.assertFalse(
                os.path.exists(os.path.join(
                    self.tmp, "not_a_real_material_rgb.bsdf")),
                "a bad download was kept and would poison this material "
                "permanently - the file exists, so it is never refetched")
        finally:
            matx_sources.download = real_download

    def test_a_poisoned_cache_heals_itself(self):
        import os
        target = os.path.join(self.tmp, "stale_rgb.bsdf")
        with open(target, "wb") as handle:
            handle.write(b"garbage from a previous session")
        self.assertFalse(matx_sources.RGLSource._is_measurement(target))
        record = matx_sources.MatxRecord(
            source="RGL", uid="stale", title="Stale",
            kind="values", payload={})
        real_download = matx_sources.download
        calls = []

        def fake_download(url, path, on_bytes=None, **kwargs):
            calls.append(url)
            with open(path, "wb") as handle:
                handle.write(b"<html>still broken</html>")

        matx_sources.download = fake_download
        try:
            with self.assertRaises(ValueError):
                self.rgl.fetch(record, None, self.tmp)
            self.assertTrue(calls, "the poisoned cache was reused, not "
                                   "refetched")
        finally:
            matx_sources.download = real_download

    TRUNCATED = b"tensor_file\0" + bytes([1, 0]) + struct.pack("<I", 5)    # the magic, then nothing

    def _served(self, body) -> list:
        """The network door answering every request with `body`; answers the URLs asked."""
        from unittest import mock
        from amaze.tests.test_packages import _Served
        asked = []

        def serve(url, headers=None):
            asked.append(url)
            return _Served(body, {"Content-Length": str(len(body))})

        patcher = mock.patch.object(matx_sources, "_request", serve)
        patcher.start()
        self.addCleanup(patcher.stop)
        return asked

    def _cached(self, uid, body):
        record = matx_sources.MatxRecord(source="RGL", uid=uid, title=uid, kind="values",
                                         payload={})
        target = os.path.join(self.tmp, "%s_rgb.bsdf" % uid)
        with open(target, "wb") as handle:
            handle.write(body)
        return record, target

    def test_a_cached_measurement_that_does_not_parse_is_fetched_once_more(self):
        good = os.path.join(self.tmp, "good.bsdf")
        _tensor_file(good, [RGLRoughnessTest.WIDE] * 2)
        with open(good, "rb") as handle:
            asked = self._served(handle.read())
        record, target = self._cached("truncated", self.TRUNCATED)
        try:
            got = self.rgl.fetch(record, None, self.tmp)
        except Exception as exc:                             # noqa: BLE001
            self.fail("the unreadable cache was not fetched again: %s" % exc)
        self.assertEqual(1, len(asked), asked)
        self.assertIn("roughness", got["values"])
        self.assertTrue(matx_sources.RGLSource._is_measurement(target))

    def test_a_measurement_that_does_not_parse_twice_is_refused_in_one_sentence(self):
        asked = self._served(self.TRUNCATED)
        record, target = self._cached("truncated", self.TRUNCATED)
        with self.assertRaises(Exception) as refused:
            self.rgl.fetch(record, None, self.tmp)
        self.assertEqual("truncated did not return a measurement (the download is not a "
                         "tensor_file)", str(refused.exception))
        self.assertEqual(1, len(asked), "the refetch was not asked exactly once")
        self.assertFalse(os.path.exists(target), "an unreadable measurement stayed cached")


class ThirdPartyHostTest(unittest.TestCase):
    """Third-party URLs are not ours to rename - the LITERAL hosts are asserted so a future rename fails immediately instead of a feature failing quietly weeks later. ▸r/matx-source-quirks"""

    def test_the_gpuopen_api_host_is_amds(self):
        from amaze.core import matx_sources

        self.assertEqual("https://api.matlib.gpuopen.com/api",
                         matx_sources.GPUOpenSource.API)

    def test_no_source_url_carries_our_app_name(self):
        """Our name has no business inside anyone else's domain."""
        import inspect

        from amaze.core import matx_sources

        source = inspect.getsource(matx_sources)
        offenders = re.findall(
            r"https?://[^\s\"']*amaze[^\s\"']*", source, re.I)
        offenders = [u for u in offenders
                     if "github.com/Timour" not in u
                     and "api.github.com/repos/Timour" not in u
                     and "raw.githubusercontent.com/Timour" not in u]    # our own repos, GitHub-hosted - the pin is about OUR name inside a third party's domain
        self.assertEqual([], offenders,
                         "a third-party URL contains our app name")


class TruncatedDownloadTest(unittest.TestCase):
    """A short transfer must never be promoted as a finished file - HTTPResponse does not raise on a short body, so the read loop exits normally and the promote would land the fragment. ▸r/matx-source-quirks"""

    def _serve_once(self, body: bytes, declared_length=None) -> str:
        """A one-shot HTTP server that can lie about Content-Length, answering its URL."""
        import socket
        import threading

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        port = srv.getsockname()[1]

        def serve():
            try:
                conn, _ = srv.accept()
                conn.recv(65536)
                head = b"HTTP/1.1 200 OK\r\n"
                if declared_length is not None:
                    head += b"Content-Length: %d\r\n" % declared_length
                head += b"Connection: close\r\n\r\n"
                conn.sendall(head + body)
                conn.close()
            except OSError:
                pass          # the test finished first - nothing to serve

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        widened = matx_sources.ALLOWED_SCHEMES + ("http",)    # plain http on loopback, said out loud: widened for this test's lifetime, never the product's rule loosened
        original = matx_sources.ALLOWED_SCHEMES
        matx_sources.ALLOWED_SCHEMES = widened
        self.addCleanup(
            setattr, matx_sources, "ALLOWED_SCHEMES", original)
        return "http://127.0.0.1:%d/file.bsdf" % port

    def _dest(self) -> str:
        import tempfile
        return os.path.join(tempfile.mkdtemp(prefix="amaze_trunc_"), "f.bsdf")

    def test_a_truncated_transfer_is_refused(self):
        url = self._serve_once(b"x" * 1000, declared_length=100000)
        dest = self._dest()
        with self.assertRaises(OSError) as caught:
            matx_sources.download(url, dest)
        self.assertIn("truncated", str(caught.exception))
        self.assertFalse(
            os.path.exists(dest),
            "a truncated transfer was promoted to the final path, where "
            "every cache layer treats it as a finished download forever")
        self.assertFalse(os.path.exists(dest + ".part"),
                         "the partial file was left behind")

    def test_a_complete_transfer_still_lands(self):
        """The guard must not be so strict it refuses good downloads."""
        for body, declared in ((b"y" * 5000, 5000), (b"z" * 300, None)):    # no Content-Length is no lie
            with self.subTest(declared=declared):
                url = self._serve_once(body, declared_length=declared)
                dest = self._dest()
                matx_sources.download(url, dest)
                self.assertEqual(len(body), os.path.getsize(dest))


class SilentOnlineFailureTest(unittest.TestCase):
    """An unreachable host must never look like an empty catalogue (the bug class that hid a corrupted hostname for a day, ▸r/matx-source-quirks) - asserted on the LOG via captured_log(), the one channel both platforms share, because note() returns before its print on Windows (research.md ▸ Debug log)."""

    def setUp(self):
        self.real_json = matx_sources.get_json
        self.addCleanup(setattr, matx_sources, "get_json", self.real_json)

    def _dead(self, *args, **kwargs):
        raise OSError("nodename nor servname provided")

    def _source(self, name):
        return [s for s in matx_sources.all_sources() if s.name == name][0]

    def test_polyhaven_resolutions_reports_an_unreachable_host(self):
        source = self._source("PolyHaven")
        record = matx_sources.MatxRecord(
            source="PolyHaven", uid="aerial_asphalt_01",
            title="Aerial Asphalt 01", kind="package", payload={})
        matx_sources.get_json = self._dead

        with test_support.captured_log() as log:
            self.assertEqual([], source.resolutions(record))
        said = log.matching("could not reach")
        self.assertTrue(
            said,
            "a dead host produced an empty resolution list and said "
            "nothing - indistinguishable from a material with no mtlx")
        self.assertIn("PolyHaven", said[0],    # ONE record and the assertions are on IT, or a sentence can be deleted with the test still green (practice.md ▸ Testing)
                      "the message does not name the site that is down, "
                      "so it cannot be told from any other failure: %r"
                      % said[0])
        self.assertIn("Aerial Asphalt 01", said[0],
                      "the message does not name the material the user "
                      "clicked: %r" % said[0])

    def test_gpuopen_does_not_cache_a_failed_category_lookup(self):
        """A failure cached as {} filed every material under Uncategorized for the run with nothing retrying. ▸r/matx-source-quirks"""
        source = self._source("GPUOpen")
        source._categories = None
        matx_sources.get_json = self._dead

        with test_support.captured_log():
            self.assertEqual({}, source._category_map())
        self.assertIsNone(
            source._categories,
            "a failed category lookup was cached - every later call "
            "returns Uncategorized without retrying")

        calls = []
        matx_sources.get_json = lambda *a, **k: (    # the API back: the next call works, then is cached
            calls.append(1), {"results": [{"id": "u1", "title": "Metal"}]})[1]
        self.assertEqual({"u1": "Metal"}, source._category_map())
        source._category_map()
        self.assertEqual(1, len(calls),
                         "the category map is no longer cached on success")


class MtlxRepairHonestyTest(unittest.TestCase):
    """A repair that could not be WRITTEN is not a repair - the swallowed rewrite once logged success while every texture rendered black. ▸r/matx-source-quirks"""

    def setUp(self):
        import tempfile
        self.dest = tempfile.mkdtemp(prefix="amaze_mtlx_")
        self.addCleanup(__import__("shutil").rmtree, self.dest, True)
        self.mtlx = os.path.join(self.dest, "material.mtlx")    # the document references .exr; only .jpg was fetched
        with open(self.mtlx, "w", encoding="utf-8") as handle:
            handle.write('<materialx><input value="tex_rough_1k.exr"/>'
                         "</materialx>")
        with open(os.path.join(self.dest, "tex_rough_1k.jpg"), "wb") as handle:
            handle.write(b"\xff\xd8\xff")

    def test_a_writable_document_reports_the_repair(self):
        repairs = matx_sources.repair_mtlx_references(self.mtlx, self.dest)
        self.assertTrue(repairs, "the inconsistency was not detected")
        self.assertEqual("tex_rough_1k.jpg", repairs[0]["fixed_to"])

    def test_an_unwritable_document_reports_NO_repair(self):
        os.chmod(self.mtlx, 0o444)
        self.addCleanup(os.chmod, self.mtlx, 0o644)
        with test_support.captured_log() as log:
            repairs = matx_sources.repair_mtlx_references(
                self.mtlx, self.dest)
        if not repairs:
            self.skipTest("running as a user who can write read-only files")
        self.assertIsNone(
            repairs[0]["fixed_to"],
            "a repair that could not be written was reported as done - "
            "the material renders black while the log says success")
        # the CAUSE is what this function owes; the caller owns the consequence, or the user gets the same bad news twice
        self.assertTrue(
            log.matching("could not be updated"),
            "a failed rewrite was marked unrepaired but never said why, "
            "so the log cannot tell it from a material with no textures "
            "to repair: %r" % (log.messages(),))


class MtlxRepairFindsTheColourMapUnderItsOtherNames(unittest.TestCase):
    """Poly Haven's document says `_diff_` while the map it ships is `_col1_`, `_coll1_` or `_albedo_` - a different stem, which the extension repair cannot see, and the material came in with no colour map at all. ▸r/matx-source-quirks"""

    def _package(self, shipped):
        import tempfile
        dest = tempfile.mkdtemp(prefix="amaze_mtlx_col_")
        self.addCleanup(__import__("shutil").rmtree, dest, True)
        mtlx = os.path.join(dest, "material.mtlx")
        with open(mtlx, "w", encoding="utf-8") as handle:
            handle.write('<materialx><input value="textures/leather_red_02_diff_2k.jpg"/>'
                         "</materialx>")
        os.makedirs(os.path.join(dest, "textures"))
        with open(os.path.join(dest, "textures", shipped), "wb") as handle:
            handle.write(b"\x89PNG")
        return mtlx, dest

    def test_each_synonym_is_found(self):
        for shipped, taken in (("leather_red_02_col1_2k.png", True),
                               ("leather_red_02_coll1_2k.png", True),
                               ("leather_red_02_albedo_2k.jpg", True),
                               ("leather_red_02_rough_2k.png", False)):    # another role's map
            with self.subTest(shipped=shipped):
                mtlx, dest = self._package(shipped)
                repairs = matx_sources.repair_mtlx_references(mtlx, dest)
                self.assertEqual(
                    "textures/" + shipped if taken else None,
                    repairs[0]["fixed_to"] if repairs else None,
                    "the map shipped as %s was wired the wrong way for "
                    "the document's diff reference" % shipped)


class PartialCatalogueTest(unittest.TestCase):
    """A catalogue missing a whole source must not become the baseline - a COLD cache once adopted a GPUOpen-down fetch and every later run matched and accepted it, the source permanently absent while the menu still listed it."""

    def setUp(self):
        from amaze.core import matx_library

        self.matx_library = matx_library
        self.model = matx_library.MatxOnlineLibrary.__new__(
            matx_library.MatxOnlineLibrary)
        self.model._loading = True    # only what _on_catalogue touches - constructing the real model starts threads and hits the network
        self.model._generation = 0
        self.model._all = []
        self.model._error = ""
        self.model._loaded = False
        self.saved = []
        self.model._save_cache = self.saved.append
        self.model._apply_filter = lambda *a, **k: None
        self.model._source_filter = None

    def _records(self, count):
        return [matx_sources.MatxRecord(
            source="GPUOpen", uid="u%d" % i, title="M%d" % i,
            kind="package", payload={}) for i in range(count)]

    def test_a_partial_fetch_is_not_written_to_a_cold_cache(self):
        with test_support.captured_log() as log:
            self.model._on_catalogue(
                self._records(934), ["GPUOpen: URLError: down"], 0)
        self.assertEqual(
            [], self.saved,
            "an incomplete catalogue was cached - the missing source "
            "stays missing on every later run")
        said = log.matching("not kept")
        self.assertTrue(
            said,
            "a short list was shown with nothing said about it, so it "
            "reads exactly like the sites having nothing: %r"
            % (log.messages(),))
        self.assertIn("1", said[0],
                      "the message does not say HOW MANY sites are "
                      "missing from the list: %r" % said[0])
        self.assertEqual(934, len(self.model._all),
                         "not caching cost the user the tiles that loaded")
        self.assertTrue(self.model._loaded)

    def test_a_complete_fetch_is_cached(self):
        self.model._on_catalogue(self._records(1388), [], 0)
        self.assertEqual(
            1, len(self.saved), "a complete catalogue was not cached")

    def test_the_error_carries_a_reason(self):
        """errors once recorded only the exception TYPE, which a dozen causes share."""
        worker = self.matx_library._CatalogueWorker([], 0)

        class _Dead:
            name = "GPUOpen"

            def list_materials(self, **kwargs):
                raise OSError("nodename nor servname provided")

        worker._sources = [_Dead()]
        captured = {}
        worker.done = type("S", (), {
            "emit": lambda _self, r, e, g: captured.update(errors=e)})()
        worker.run()
        self.assertTrue(captured["errors"])
        self.assertIn("nodename", captured["errors"][0],
                      "the failure reason was dropped: %s"
                      % captured["errors"][0])


class NoNetworkBeforeTheProgressBarTest(unittest.TestCase):
    """Deciding whether to SHOW a progress bar must not cost requests - routing through the resolution lookup once blocked Houdini on ~50 serial GETs for a ten-material selection, measured here as 60 stubbed requests against the 0 the question needs."""

    def setUp(self):
        self.real_json = matx_sources.get_json
        self.addCleanup(setattr, matx_sources, "get_json", self.real_json)
        self.calls = []
        matx_sources.get_json = lambda url, *a, **k: (
            self.calls.append(url), {"results": []})[1]

    def _records(self, source_name, kind="package", count=10):
        return [matx_sources.MatxRecord(
            source=source_name, uid="u%d" % i, title="M%d" % i, kind=kind,
            payload={"packages": ["p%d-%d" % (i, j) for j in range(6)]})
            for i in range(count)]

    def test_needs_download_never_touches_the_network(self):
        for source in matx_sources.all_sources():
            self.calls.clear()
            for record in self._records(source.name):
                source.needs_download(record)
            self.assertEqual(
                [], self.calls,
                "%s.needs_download made %d request(s) - the progress-bar "
                "decision blocks the UI thread"
                % (source.name, len(self.calls)))

    def test_both_doors_find_a_records_source_one_way(self):
        """The bar's question and the import's find the same source by name, or none."""
        panel = test_support.fixture_panel(self)
        named = panel.matx_online_model.sources[0]
        record = self._records(named.name, kind="values", count=1)[0]
        stray = self._records("Nowhere", count=1)[0]
        self.assertIs(named, panel._online_source_for(record)[0])
        self.assertEqual((None, None, "Unknown source Nowhere"),
                         panel._online_source_for(stray))
        self.assertFalse(panel._needs_download([stray]))
        self.assertEqual([], self.calls, "a source lookup reached the network")
        model = panel.matx_online_model
        self.assertIsNone(model.source_for(stray))
        for named in model.sources:
            with self.subTest(source=named.name):
                self.assertIs(named, model.source_for(
                    self._records(named.name, count=1)[0]))
                self.calls.clear()
                panel._needs_download(self._records(named.name))
                self.assertEqual(
                    [], self.calls,
                    "the progress-bar question resolved a download "
                    "resolution - one HTTP GET per package on the UI thread")


class CertificateVerificationTest(unittest.TestCase):
    """Online requests must VERIFY, not just connect - the CERT_NONE retry keyed on the parent class fired on certificate failure itself, and with no system CA chain in Houdini's Python that was the NORMAL path. ▸r/matx-network-hardening"""

    def test_the_shared_context_verifies(self):
        import ssl
        ctx = matx_sources._ssl_context()
        self.assertEqual(
            ssl.CERT_REQUIRED, ctx.verify_mode,
            "online requests are not verifying certificates")
        self.assertTrue(
            ctx.check_hostname,
            "hostname checking is off - any valid certificate would pass")
        self.assertTrue(
            ctx.get_ca_certs(),
            "the SSL context trusts no certificate authorities, so every "
            "https request will fail into the unverified retry")

    def test_a_non_ssl_error_is_not_retried_unverified(self):
        """A 404 or a timeout must not reach a relaxed retry - counted at the OPENER, because the seam moved there with the redirect handler and a urlopen patch counts zero while passing for the wrong reason."""
        import urllib.error

        real = matx_sources.urllib.request.build_opener
        calls = []

        class _Refusing:
            def open(self, req, *args, **kwargs):
                calls.append(req)
                raise urllib.error.URLError(OSError("connection refused"))

        matx_sources.urllib.request.build_opener = \
            lambda *args, **kwargs: _Refusing()
        try:
            with self.assertRaises(urllib.error.URLError):
                matx_sources._request("https://example.invalid/thing")
        finally:
            matx_sources.urllib.request.build_opener = real
        self.assertEqual(
            1, len(calls),
            "a non-SSL failure was retried with verification disabled")


if __name__ == "__main__":
    unittest.main()
