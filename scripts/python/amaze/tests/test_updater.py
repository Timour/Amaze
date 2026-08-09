"""Is there a newer Amaze, and can this one become it?

Every test here mocks the single network door; none reaches GitHub.
The feed's real answers were measured once
(research.md > GitHub's release feed) and are reproduced as fixtures.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import branding                                # noqa: E402
from amaze.core import matx_sources, updater              # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401


class _Response(io.BytesIO):
    """What urlopen hands back, as a context manager with headers."""

    def __init__(self, payload, headers=None):
        super().__init__(payload if isinstance(payload, bytes)
                         else json.dumps(payload).encode("utf-8"))
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _FeedMixin(unittest.TestCase):

    def answer(self, payload=None, headers=None, raising=None):
        """Point the ONE network door at a fixture."""
        calls = []

        def fake(url):
            calls.append(url)
            if raising is not None:
                raise raising
            return _Response(payload, headers)

        real = matx_sources._request
        matx_sources._request = fake
        self.addCleanup(setattr, matx_sources, "_request", real)
        return calls


class TheVersionComparisonTest(unittest.TestCase):

    def test_a_longer_version_is_newer_than_its_prefix(self):
        self.assertTrue(updater.is_newer("1.0.1", "1.0"))
        self.assertFalse(updater.is_newer("1.0", "1.0.1"))

    def test_the_leading_v_is_optional_on_either_side(self):
        """Measured in the wild: vscode tags `1.132.0`, node `v26.7.0`."""
        self.assertTrue(updater.is_newer("v2.0", "1.9"))
        self.assertFalse(updater.is_newer("v1.0", "1.0"))

    def test_the_same_version_is_not_newer(self):
        self.assertFalse(
            updater.is_newer(branding.APP_VERSION, branding.APP_VERSION))

    def test_ten_sorts_above_nine_rather_than_beside_it(self):
        self.assertTrue(updater.is_newer("1.10", "1.9"),
                        "versions compared as text put 1.10 below 1.9")

    def test_an_unreadable_piece_does_not_raise(self):
        updater.parts("v1.2.3-rc1+build")
        self.assertFalse(updater.is_newer("", "1.0"))


class TheCheckTest(_FeedMixin):

    def test_no_release_yet_is_reported_gracefully(self):
        """The ordinary answer until 1.0 is tagged: measured 404 with
        a Not Found body, on a repo that itself answers 200."""
        self.answer(raising=urllib.error.HTTPError(
            updater.RELEASES_URL, 404, "Not Found", {}, None))
        result = updater.check("1.0")
        self.assertEqual(updater.NO_RELEASE, result.verdict)
        self.assertFalse(result)
        self.assertIn("1.0", result.sentence)
        self.assertNotIn("error", result.sentence.lower(),
                         "no release yet is not a failure and must not "
                         "read like one")

    def test_a_newer_release_is_offered_with_its_download(self):
        self.answer({"tag_name": "v1.1",
                     "zipball_url": "https://example.invalid/z",
                     "assets": []})
        result = updater.check("1.0")
        self.assertEqual(updater.NEWER, result.verdict)
        self.assertTrue(result)
        self.assertEqual("v1.1", result.version)
        self.assertEqual("https://example.invalid/z", result.url)

    def test_a_release_with_no_assets_still_has_a_download(self):
        """Measured: `assets` is empty on plenty of real releases, so
        looking only there offers an update that cannot be fetched."""
        self.answer({"tag_name": "9.9", "assets": [],
                     "zipball_url": "https://example.invalid/src.zip"})
        self.assertTrue(updater.check("1.0").url,
                        "a source-only release came back with no URL")

    def test_an_uploaded_zip_wins_over_the_source_archive(self):
        self.answer({"tag_name": "9.9",
                     "zipball_url": "https://example.invalid/src",
                     "assets": [{"name": "amaze.zip",
                                 "browser_download_url":
                                 "https://example.invalid/built.zip"}]})
        self.assertEqual("https://example.invalid/built.zip",
                         updater.check("1.0").url)

    def test_the_same_version_reports_up_to_date(self):
        self.answer({"tag_name": "1.0", "assets": []})
        self.assertEqual(updater.UP_TO_DATE, updater.check("1.0").verdict)

    def test_an_unreachable_feed_changes_nothing_and_says_so(self):
        self.answer(raising=urllib.error.URLError("offline"))
        result = updater.check("1.0")
        self.assertEqual(updater.UNREACHABLE, result.verdict)
        self.assertIn("nothing has been changed", result.sentence.lower())

    def test_a_release_with_no_tag_cannot_be_compared(self):
        self.answer({"assets": []})
        self.assertEqual(updater.NO_RELEASE, updater.check("1.0").verdict)

    def test_the_check_asks_the_releases_endpoint_once(self):
        calls = self.answer({"tag_name": "1.0", "assets": []})
        updater.check("1.0")
        self.assertEqual([updater.RELEASES_URL], calls,
                         "the check must cost exactly one call - the "
                         "unauthenticated limit is 60 an hour")


class TheDownloadTest(_FeedMixin):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_update_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_a_complete_download_is_kept(self):
        self.answer(b"PK\x03\x04zipbody",
                    headers={"Content-Length": str(len(b"PK\x03\x04zipbody"))})
        path = updater.download("https://example.invalid/z", self.dir)
        self.assertTrue(os.path.exists(path))

    def test_a_truncated_download_is_refused_and_removed(self):
        """A short body closes the connection and the read loop ends
        NORMALLY, so nothing raises on its own (research.md). Without
        the length check a truncated archive is promoted as valid."""
        self.answer(b"PK\x03\x04", headers={"Content-Length": "9999"})
        with self.assertRaises(OSError) as caught:
            updater.download("https://example.invalid/z", self.dir)
        self.assertIn("stopped early", str(caught.exception))
        self.assertEqual([], os.listdir(self.dir),
                         "the partial file was left behind")

    def test_an_empty_download_is_refused(self):
        self.answer(b"", headers={})
        with self.assertRaises(OSError):
            updater.download("https://example.invalid/z", self.dir)

    def test_a_missing_length_is_unknown_rather_than_zero(self):
        """Treating an absent Content-Length as 0 would refuse every
        server that does not send one."""
        self.answer(b"PK\x03\x04body", headers={})
        self.assertTrue(
            os.path.exists(updater.download("https://x.invalid/z", self.dir)))


class TheSwapTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_swap_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.install = os.path.join(self.root, "install")
        self.staged = os.path.join(self.root, "staged")
        for path, marker in ((self.install, "old"), (self.staged, "new")):
            os.makedirs(path)
            with open(os.path.join(path, "which.txt"), "w",
                      encoding="utf-8") as handle:
                handle.write(marker)

    def _which(self, path):
        with open(os.path.join(path, "which.txt"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_new_install_takes_the_place_of_the_old(self):
        backup = updater.apply_update(self.staged, self.install)
        self.assertEqual("new", self._which(self.install))
        self.assertEqual("old", self._which(backup),
                         "the previous install must survive as .backup")

    def test_a_second_update_does_not_trip_on_the_old_backup(self):
        updater.apply_update(self.staged, self.install)
        os.makedirs(self.staged)
        with open(os.path.join(self.staged, "which.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write("newer")
        updater.apply_update(self.staged, self.install)
        self.assertEqual("newer", self._which(self.install))

    def test_a_missing_staged_update_leaves_the_install_alone(self):
        with self.assertRaises(OSError):
            updater.apply_update(os.path.join(self.root, "nothing"),
                                 self.install)
        self.assertEqual("old", self._which(self.install),
                         "the install was disturbed by an update that "
                         "was never there to apply")


class TheNetworkDoorTest(unittest.TestCase):

    def test_the_updater_opens_no_url_of_its_own(self):
        """One `urlopen` in the package, or the suite's network block
        does not cover this module (practice.md)."""
        with open(os.path.abspath(updater.__file__.replace(".pyc", ".py")),
                  encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn(
            "urlopen", body,
            "updater.py calls urlopen directly, so fixture_panel's block "
            "on matx_sources._request does not stop it and a test could "
            "reach GitHub")

    def test_nothing_checks_for_updates_at_import(self):
        self.assertNotIn(
            "check()", open(
                os.path.abspath(updater.__file__.replace(".pyc", ".py")),
                encoding="utf-8").read().split("def check")[0],
            "something calls check() before any caller asks - the feed "
            "is only ever consulted on request")


if __name__ == "__main__":
    unittest.main()
