"""The Generator Engine: the invariants a generated material must hold.

Generation is random, so these tests assert PROPERTIES over a large
sample rather than exact values: every generated material must be
physically coherent (no transmissive metal), in range, renderable (not
black), and honest about where its numbers came from.

The facts themselves are shipped tables, so this needs no network.
"""

import collections
import colorsys
import os
import random
import sys
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

# THREE dirnames: tests/ -> amaze/ -> python/, the directory that
# holds the `amaze` package. The original had four, which lands on
# scripts/ - where amaze is NOT importable - so every one of these
# files silently imported amaze through Houdini's own package path,
# i.e. the INSTALL. The sync-before-test discipline masked it for the
# suite's whole life; it surfaced when a deliberately-unsynced
# sabotage edit failed to change a test's behaviour.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import matx_sources  # noqa: E402
from amaze.render import generator, nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log

#: Enough samples that a 1-in-100 rule (emission) is exercised.
SAMPLES = 400


class TestFacts(unittest.TestCase):
    """The shipped corpus the generator reads."""

    def test_both_sources_ship(self):
        facts = generator.online_facts()
        sources = collections.Counter(f["source"] for f in facts)
        self.assertGreater(sources["PhysicallyBased"], 50)
        self.assertGreater(sources["RGL"], 50)

    def test_every_class_is_represented(self):
        kinds = collections.Counter(
            generator.fact_kind(f) for f in generator.online_facts()
        )
        for kind in ("metal", "transmissive", "subsurface", "opaque"):
            self.assertGreater(kinds[kind], 0, "no %s facts" % kind)

    def test_metals_carry_a_measured_finish(self):
        """The reference set lists metals as perfect mirrors; the
        measured set is what gives a generated metal its surface. If
        that half ever goes missing, metals silently become mirrors."""
        rough = [f["roughness"] for f in generator.online_facts()
                 if generator.fact_kind(f) == "metal" and f["roughness"] > 0]
        self.assertGreaterEqual(len(rough), 5)

    def test_classifier_rejects_the_substring_trap(self):
        """The CLASSIFIER, not a pre-classified dict: "tin" is a
        substring of "satin", which made the whole TeckWrap vinyl range
        metal. (The earlier version of this test fed _normalise a dict
        that already said metalness 0 and could never fail.)"""
        infer = matx_sources.RGLSource.infer_metal
        self.assertFalse(infer("satin_blue",
                               "TeckWrap vinyl wrapping film"))
        self.assertFalse(infer("vch_golden_yellow",
                               "TeckWrap vinyl wrapping film"))
        self.assertTrue(infer("aniso_brushed_aluminium_1",
                              "Brushed aluminium sheet"))

    def test_classifier_trusts_the_measurement_over_the_name(self):
        """No bare conductor is dark: a "metallic" coating measuring
        0.09 is a dark paint, not a metal (as a conductor it renders as
        an almost black mirror)."""
        infer = matx_sources.RGLSource.infer_metal
        self.assertFalse(infer("ilm_solo_m_68", "Blue metallic material",
                               [0.022, 0.033, 0.091]))
        self.assertTrue(infer("aniso_copper_sheet", "Smooth copper sheet",
                              [0.95, 0.63, 0.53]))

    def test_paint_is_a_dielectric_whatever_it_is_sprayed_on(self):
        """"flake paint ON TOP OF ALUMINIUM" matched the substrate and
        came out metal, while its identical sibling came out
        dielectric."""
        infer = matx_sources.RGLSource.infer_metal
        self.assertFalse(infer(
            "irid_flake_paint1",
            "Iridescent flake car paint on top of aluminium with black "
            "primer", [0.3, 0.2, 0.4]))

    def test_no_negative_colour_channels(self):
        """Measurement noise around black produced negative channels;
        a negative base_color is not a colour."""
        for fact in generator.online_facts():
            for channel in fact["color"]:
                self.assertGreaterEqual(channel, 0.0, fact["name"])

    def test_metal_finish_pool_excludes_saturated_fits(self):
        """A GGX alpha of exactly 1.0 is the ceiling of the fit, not a
        measurement - a metal must not inherit it as its finish."""
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
        """A black material renders as a hole - the one result that is
        never worth generating."""
        for spec, prov in self.samples:
            self.assertGreater(sum(spec.get("base_color", [0, 0, 0])), 0.0,
                               prov)

    def test_metals_keep_a_metal_spectrum(self):
        """A metal's colour is its reflectance spectrum. Hue-rotating
        copper produces a metal that exists nowhere, so generated
        metals stay inside the gamut the measurements occupy."""
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
        """Water is 1.333 or it is not water: the IOR is copied, never
        varied. The ONE exception is a source IOR of 1.0 - Soap Bubble
        refracts nothing and its look is the thin film, so copying 1.0
        "exactly" generates an invisible material."""
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
        """The unit bug this codebase has already been bitten by: the
        radius is a mean free path in CENTIMETRES and reaches the
        shader with subsurface_scale converting it to scene metres."""
        checked = 0
        for spec, prov in self.samples:
            if spec.get("subsurface", 0.0) <= 0.0:
                continue
            checked += 1
            self.assertEqual(spec["subsurface_scale"],
                             generator.CM_TO_SCENE_UNITS, prov)
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
        """The module's headline claim: clearcoat on about a third,
        emission on almost none - measured, not invented."""
        rates = generator.character_rates()
        self.assertGreater(rates["coat"], 0.2)
        self.assertLess(rates["coat"], 0.5)
        self.assertLess(rates["emission"], 0.05)
        coated = [s for s, _ in self.samples if s.get("coat", 0.0) > 0.0]
        share = len(coated) / float(len(self.samples))
        # Metals and opaque dielectrics are the eligible classes, so the
        # observed share is the rate scaled by their share of the corpus.
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
        """The satin trap once more, in the generator's OWN class
        table: a colourway name must not beat the description."""
        fact = generator._normalise("RGL", "satin_blue", {
            "color": [0.68, 0.74, 0.75], "metalness": 0.0,
            "roughness": 0.3,
            "description": "TeckWrap vinyl wrapping film (Blue Satin)",
        })
        self.assertEqual(fact["classes"], ["Film"])
        self.assertFalse(generator._is_fabric(fact))

    def test_every_spec_key_exists_on_the_shader(self):
        """A key the shader does not have is set silently into
        nothing."""
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


class TestCatalogueFreshness(unittest.TestCase):
    """New materials on the sites must simply APPEAR - browsing a
    catalogue should behave like browsing the website, not like
    software with an update prompt. And with no network, the shipped
    tables ARE the catalogue, so browsing keeps working on a plane.

    Both are safe to do eagerly because list_materials is only ever
    called from the catalogue worker thread (core/matx_library).
    """

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
        """Reachable is not correct. A captive portal, a proxy error
        page or a schema change all return valid JSON; accepting one
        blindly replaced 86 measured materials with whatever came
        back, and the browser showed a handful of grey tiles."""
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

    #: A response that _usable() should ACCEPT: a list of entries that
    #: each carry a name and a three-channel colour.
    GOOD_PAYLOAD = [{"name": "live%d" % i, "color": [0.4, 0.4, 0.4]}
                    for i in range(30)]

    def _pb(self):
        return [s for s in self._sources() if s.name == "PhysicallyBased"][0]

    def _without_the_shipped_table(self, pb):
        """Point _table_path at a file that does not exist, and return the
        real bound method so the caller can put it back."""
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
        """The path the test above cannot reach.

        With the shipped table READABLE a bad payload is simply ignored,
        so the fallback's own re-fetch was never exercised - and that
        re-fetch assigned the response with no shape check at all, the
        one way around the gate. A missing table plus a captive portal is
        enough: the portal's JSON became the catalogue, and because
        everything downstream slices it as a list, a JSON object surfaced
        as a TypeError several calls from its cause.
        """
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
        """The ACCEPT path of the same branch.

        The case that makes the re-fetch worth keeping: the first request
        fails transiently and there is no table to fall back on. Gating
        the retry must not have turned that into a refusal.
        """
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
                # Caught and turned into a NAMED failure on purpose: an
                # over-strict gate raises here, and a bare traceback
                # would report "something threw" rather than the claim
                # this test is making.
                self.fail("a good response on the retry was refused (%s), "
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
        """A material the site lists and the table does not must still
        appear - that is what "new materials just show up" means."""
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


class TestDownloadIntegrity(unittest.TestCase):
    """Anything fetched from the network is data, not truth.

    The live catalogue now lists RGL materials the shipped table has
    never seen, so importing one DOWNLOADS a measurement - and a cached
    file is never re-fetched, which makes one bad response permanent.
    """

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

        # THE REAL SIGNATURE, positional third argument included.
        # `download(url, dest, on_bytes=None)` is called positionally by
        # the RGL fetch, and a **kwargs-only stub took the call as an
        # arity error - a stub that does not match the thing it stands
        # in for fails on the day the real call grows an argument.
        def fake_download(url, target, on_bytes=None, **kwargs):
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


class ThirdPartyHostTest(unittest.TestCase):
    """Third-party URLs are not ours to rename.

    A blind matlib->amaze substring replace on 2026-07-27 rewrote AMD's
    api.matlib.gpuopen.com to api.amaze.gpuopen.com, a host that does
    not resolve. Browsing still worked - it reads the shipped offline
    table - so nothing looked wrong until an import failed with "no
    downloadable package", because the catalogue fetch died inside an
    `except Exception: continue`.

    These assert the LITERAL hosts. If a future rename touches them the
    test fails immediately, instead of a feature failing quietly weeks
    later."""

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
        offenders = [u for u in offenders if "github.com/Timour" not in u]
        self.assertEqual([], offenders,
                         "a third-party URL contains our app name")


class TruncatedDownloadTest(unittest.TestCase):
    """A short transfer must never be promoted as a finished file.

    download() streams into a .part and os.replace()s it, and the
    docstring took that to mean a cut-off transfer could not leave a
    truncated file. It could: CPython's HTTPResponse.readinto does NOT
    raise on a short body - it closes the connection and returns 0 - so
    the read loop exits NORMALLY and os.replace promotes the fragment.

    Nothing downstream catches it. A truncated .bsdf still passes RGL's
    12-byte "tensor_file" magic check, so it lands in the cache and is
    never re-fetched: that material is dead permanently, which is the
    exact poisoning TestDownloadIntegrity above exists to prevent. A
    truncated PolyHaven texture lands in the library and renders wrong.
    All four hosts send Content-Length, so one check covers them all."""

    def _serve_once(self, body: bytes, declared_length=None) -> str:
        """A one-shot HTTP server that can lie about Content-Length.
        Returns its URL."""
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
        # PLAIN HTTP ON LOOPBACK, said out loud. The fetcher is
        # https-only, because every URL it opens comes out of a remote
        # catalogue; this server is a real socket on 127.0.0.1 serving
        # bytes this test wrote, so the scheme rule is widened for its
        # lifetime rather than the product's rule being loosened to
        # make a test pass.
        widened = matx_sources.ALLOWED_SCHEMES + ("http",)
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

    def test_a_refused_transfer_leaves_no_part_file(self):
        url = self._serve_once(b"x" * 1000, declared_length=100000)
        dest = self._dest()
        with self.assertRaises(OSError):
            matx_sources.download(url, dest)
        self.assertFalse(os.path.exists(dest + ".part"),
                         "the partial file was left behind")

    def test_a_complete_transfer_still_lands(self):
        """The guard must not be so strict it refuses good downloads."""
        url = self._serve_once(b"y" * 5000, declared_length=5000)
        dest = self._dest()
        matx_sources.download(url, dest)
        self.assertEqual(5000, os.path.getsize(dest))

    def test_no_content_length_is_not_read_as_truncated(self):
        """A server that sends no Content-Length is not lying, and the
        progress bar already treats total=0 as unknown."""
        url = self._serve_once(b"z" * 300, declared_length=None)
        dest = self._dest()
        matx_sources.download(url, dest)
        self.assertEqual(300, os.path.getsize(dest))


class SilentOnlineFailureTest(unittest.TestCase):
    """An unreachable host must never look like an empty catalogue.

    This is the bug class that hid a corrupted API hostname for a day:
    browsing kept working off the shipped offline table, and every
    failure produced the same message a genuinely empty result does.
    GPUOpen's _packages got the "say WHY" treatment then; these three
    did not.

    Asserted on the LOG, through test_support.captured_log(). These
    diagnostics were prints when the tests were written and are
    debug.note() now, and note() returns before its print on Windows -
    research.md ▸ *Debug log*, because any print pops the Houdini
    Console. Asserting on captured stdout therefore made a test of
    HONESTY into a test of the platform: forcing hostos.is_windows()
    True turned this class red for messages that were recorded either
    way. The log is the channel both platforms share, so it is the one
    the assertion belongs on."""

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
        # ONE record, and the assertions are on IT - not on every note
        # the block wrote joined together, which is how a sentence can be
        # deleted with the test still green (practice.md ▸ Testing).
        self.assertIn("PolyHaven", said[0],
                      "the message does not name the site that is down, "
                      "so it cannot be told from any other failure: %r"
                      % said[0])
        self.assertIn("Aerial Asphalt 01", said[0],
                      "the message does not name the material the user "
                      "clicked: %r" % said[0])

    def test_gpuopen_does_not_cache_a_failed_category_lookup(self):
        """self._categories = {} before the try cached the FAILURE for
        the whole run: all 454 materials came back Uncategorized, the
        sidebar collapsed to one row, and nothing ever retried."""
        source = self._source("GPUOpen")
        source._categories = None
        matx_sources.get_json = self._dead

        with test_support.captured_log():
            self.assertEqual({}, source._category_map())
        self.assertIsNone(
            source._categories,
            "a failed category lookup was cached - every later call "
            "returns Uncategorized without retrying")

        # Recovery: the next call, with the API back, must work.
        matx_sources.get_json = lambda *a, **k: {
            "results": [{"id": "u1", "title": "Metal"}]}
        self.assertEqual({"u1": "Metal"}, source._category_map())

    def test_a_successful_category_lookup_is_still_cached(self):
        source = self._source("GPUOpen")
        source._categories = None
        calls = []

        def once(*args, **kwargs):
            calls.append(1)
            return {"results": [{"id": "u1", "title": "Wood"}]}

        matx_sources.get_json = once
        source._category_map()
        source._category_map()
        self.assertEqual(1, len(calls),
                         "the category map is no longer cached on success")


class MtlxRepairHonestyTest(unittest.TestCase):
    """A repair that could not be WRITTEN is not a repair.

    PolyHaven's API is internally inconsistent - the manifest ships
    ..._rough_1k.jpg while the .mtlx references ..._rough_1k.exr - so the
    document is rewritten to point at what was actually fetched. The
    rewrite was wrapped in `except OSError: pass`, but `repairs` already
    listed every entry as fixed_to: <path>, and matx_import logs "mtlx
    references repaired" on that basis. A read-only library or a full
    disk therefore produced a material whose textures all render BLACK
    while the log said the repair succeeded."""

    def setUp(self):
        import tempfile
        self.dest = tempfile.mkdtemp(prefix="amaze_mtlx_")
        self.addCleanup(__import__("shutil").rmtree, self.dest, True)
        # The document references .exr; only .jpg was fetched.
        self.mtlx = os.path.join(self.dest, "material.mtlx")
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
        # The CAUSE is what this function owes. It used to say "render
        # black" too, but matx_import's caller says that - with the count
        # and the material's name - and both are notes, so the user got
        # the same bad news twice for one import.
        self.assertTrue(
            log.matching("could not be updated"),
            "a failed rewrite was marked unrepaired but never said why, "
            "so the log cannot tell it from a material with no textures "
            "to repair: %r" % (log.messages(),))


class PartialCatalogueTest(unittest.TestCase):
    """A catalogue missing a whole source must not become the baseline.

    The existing guard only protects an EXISTING cache: on a COLD one
    self._all is empty, so a fetch with GPUOpen down (934 records
    instead of 1388) sailed past it and was written to disk. Every later
    run then fetched 934, matched the cache, and accepted it - GPUOpen
    permanently absent while View > Online Materials still lists it,
    because that menu is built from the static SOURCES tuple."""

    def setUp(self):
        from amaze.core import matx_library

        self.matx_library = matx_library
        self.model = matx_library.MatxOnlineLibrary.__new__(
            matx_library.MatxOnlineLibrary)
        # Only what _on_catalogue touches - constructing the real model
        # starts threads and hits the network.
        self.model._loading = True
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

    def test_a_complete_fetch_is_cached(self):
        self.model._on_catalogue(self._records(1388), [], 0)
        self.assertEqual(
            1, len(self.saved), "a complete catalogue was not cached")

    def test_a_partial_fetch_is_still_shown(self):
        """Not caching must not mean not displaying - the user should
        still see what did load."""
        with test_support.captured_log():
            self.model._on_catalogue(
                self._records(934), ["GPUOpen: URLError: down"], 0)
        self.assertEqual(934, len(self.model._all))
        self.assertTrue(self.model._loaded)

    def test_the_error_carries_a_reason(self):
        """errors used to record only the exception TYPE, which cannot
        be told apart from a dozen causes."""
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
    """Deciding whether to SHOW a progress bar must not cost requests.

    _needs_download used to route through _online_source_for, which also
    resolves the download RESOLUTION - one HTTP GET per package, on the
    main thread, before the bar is even shown. Measured live: 254 of
    GPUOpen's 454 materials carry 6 packages and 170 carry 4, so a
    ten-material selection blocked Houdini on ~50 serial requests, each
    able to stall for TIMEOUT (30s).

    Measured here with a stubbed transport: 60 requests for ten
    materials, against 0 for the question actually being asked."""

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

    def test_the_panel_asks_the_cheap_question(self):
        """Derived from the source, so a future edit cannot quietly put
        the expensive lookup back."""
        import re

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()

        match = re.search(
            r"def _needs_download\(self, records\).*?\n    def ",
            source, re.S)
        self.assertIsNotNone(match, "_needs_download not found")
        # CODE only: the comment above the fix names the call it removed,
        # and the docstring explains the whole thing.
        body = "\n".join(
            line for line in match.group(0).splitlines()
            if not line.strip().startswith("#"))
        body = re.sub(r'"""[\s\S]*?"""', "", body)
        self.assertNotIn(
            "_online_source_for", body,
            "_needs_download resolves the download resolution again - "
            "that is one HTTP GET per package on the UI thread, before "
            "the progress bar is shown")


class CertificateVerificationTest(unittest.TestCase):
    """Online requests must VERIFY, not just connect.

    _request used to retry with check_hostname=False / CERT_NONE on any
    ssl.SSLError - and ssl.SSLCertVerificationError is a SUBCLASS of it,
    so certificate-verification failure, the precise signal of an
    interception, is what switched verification off.

    That was not a rare fallback. Houdini's bundled Python carries no
    system CA chain at all (measured on 22.0.390: the default context
    has no CA certs and get_default_verify_paths().cafile is None), so
    the default context fails EVERY time and the unverified retry was
    the normal path for every catalogue fetch, preview and download.
    Houdini does ship certifi, which verifies these hosts correctly."""

    def test_the_shared_context_verifies(self):
        import ssl
        ctx = matx_sources._ssl_context()
        self.assertEqual(
            ssl.CERT_REQUIRED, ctx.verify_mode,
            "online requests are not verifying certificates")
        self.assertTrue(
            ctx.check_hostname,
            "hostname checking is off - any valid certificate would pass")

    def test_the_context_actually_has_certificates(self):
        """A verifying context with an empty trust store verifies
        nothing - it just fails. This is what the bare default context
        does under Houdini, and why certifi is used instead."""
        self.assertTrue(
            matx_sources._ssl_context().get_ca_certs(),
            "the SSL context trusts no certificate authorities, so every "
            "https request will fail into the unverified retry")

    def test_a_non_ssl_error_is_not_retried_unverified(self):
        """A 404 or a timeout must not reach the relaxed retry."""
        import urllib.error

        # THE SEAM MOVED WITH THE REDIRECT HANDLER. `_request` builds an
        # opener now instead of calling `urlopen`, so a patch on urlopen
        # intercepts nothing and this counted zero attempts while
        # passing for the wrong reason. Counting at the opener asks the
        # same question - how many times did it try?
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
