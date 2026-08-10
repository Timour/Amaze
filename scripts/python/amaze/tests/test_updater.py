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

    def test_a_failed_swap_puts_the_old_install_back(self):
        """THE WINDOW between the two renames is the only moment there
        is no install. A sabotage of the rollback stayed GREEN against
        the missing-staged test, because that one is refused before any
        rename happens - so nothing covered this until now."""
        real = os.rename
        calls = []

        def failing(src, dst):
            calls.append(src)
            if len(calls) == 2:                  # the staged -> install move
                raise OSError("the second move failed")
            return real(src, dst)

        os.rename = failing
        self.addCleanup(setattr, os, "rename", real)
        with self.assertRaises(OSError):
            updater.apply_update(self.staged, self.install)
        os.rename = real
        self.assertTrue(
            os.path.isdir(self.install),
            "the install is GONE - the first move succeeded, the second "
            "failed, and nothing put it back")
        self.assertEqual("old", self._which(self.install))

    def test_a_missing_staged_update_leaves_the_install_alone(self):
        with self.assertRaises(OSError):
            updater.apply_update(os.path.join(self.root, "nothing"),
                                 self.install)
        self.assertEqual("old", self._which(self.install),
                         "the install was disturbed by an update that "
                         "was never there to apply")


class TheNetworkDoorTest(unittest.TestCase):

    def _source(self):
        path = os.path.join(os.path.dirname(os.path.abspath(updater.__file__)),
                            "updater.py")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_the_updater_opens_no_url_of_its_own(self):
        """Scanned as a CALL, not as the word: a docstring naming the
        single door made the first version of this match itself and go
        red on prose (practice.md > grep for STRUCTURE, not prose)."""
        self.assertNotIn(
            "urlopen(", self._source(),
            "updater.py opens a URL directly, so the suite's block on "
            "matx_sources._request does not stop it and a test could "
            "reach GitHub")

    def test_the_feed_is_only_consulted_when_asked(self):
        """Nothing runs at import: a module-level call would check for
        updates on every panel open."""
        source = self._source()
        module_level = [line for line in source.splitlines()
                        if line[:1].strip() and "check(" in line
                        and not line.startswith("def ")]
        self.assertEqual(
            [], module_level,
            "something calls check() at module level, so importing the "
            "package would reach the network: %s" % module_level)


class AReleaseIsStagedIntoTheINSTALLShape(unittest.TestCase):
    """The middle of the update, which shipped missing.

    `download` writes a zip and `apply_update` demands a directory, and
    for months nothing sat between them - so the flow had no entry
    point and nobody noticed, because nothing ever ran it end to end.

    A release zip is the whole REPO. The install is four entries of it,
    the same four `sync-install.sh` places, so staging is a real step
    rather than a rename: putting the archive's own top folder where
    the install goes would install `docs/`, `tools/` and `LICENSE` over
    somebody's Houdini package."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_update_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _release_zip(self, root="owner-repo-abc1234", extras=True,
                     omit=()):
        """A zip shaped like GitHub's zipball for a tag, whose single
        top-level folder is `<owner>-<repo>-<sha>`. The SHAPE is what
        this fixture is about, so the folder is named generically."""
        import zipfile

        path = os.path.join(self.dir, "release.zip")
        # A prefix, not a format slot: with root="" the member names
        # must stay RELATIVE. `"%s/%s" % ("", entry)` writes
        # `/scripts/...`, an absolute path, which the containment check
        # rightly refuses - and would have made the flat-archive case
        # look like a product bug.
        prefix = (root + "/") if root else ""
        with zipfile.ZipFile(path, "w") as bundle:
            for entry in updater.INSTALL_ENTRIES:
                if entry in omit:
                    continue
                if entry.endswith(".xml"):
                    bundle.writestr(prefix + entry, "<menu/>")
                else:
                    bundle.writestr(prefix + entry + "/marker.txt",
                                    "from the release")
            if extras:
                bundle.writestr(prefix + "LICENSE", "GPLv3")
                bundle.writestr(prefix + "docs/architecture/overview.md", "#")
                bundle.writestr(prefix + "tools/sync-install.sh", "#!/bin/bash")
        return path

    def test_the_staged_tree_is_the_install_not_the_repo(self):
        staged = updater.stage_release(self._release_zip(),
                                       os.path.join(self.dir, "staged"))
        self.assertEqual(sorted(updater.INSTALL_ENTRIES),
                         sorted(os.listdir(staged)),
                         "the staged tree is not what the install holds")
        self.assertTrue(
            os.path.exists(os.path.join(staged, "scripts", "marker.txt")),
            "the staged tree did not carry the release's own files")

    def test_a_release_missing_an_install_entry_is_refused(self):
        with self.assertRaises(OSError) as caught:
            updater.stage_release(
                self._release_zip(omit=("toolbar",)),
                os.path.join(self.dir, "staged"))
        self.assertIn("toolbar", str(caught.exception))
        self.assertIn("Nothing has been changed", str(caught.exception))

    def test_a_member_that_escapes_the_staging_folder_is_refused(self):
        """The archive comes from a URL the release feed named, so a
        member called `../../x` writes wherever it points."""
        import zipfile

        path = os.path.join(self.dir, "evil.zip")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("../../escaped.txt", "outside")
        with self.assertRaises(OSError) as caught:
            updater.stage_release(path, os.path.join(self.dir, "staged"))
        self.assertIn("outside the update folder", str(caught.exception))
        self.assertFalse(
            os.path.exists(os.path.join(self.dir, "escaped.txt")),
            "the escaping member was written before the refusal")

    def test_a_file_that_is_not_a_zip_is_refused_with_a_sentence(self):
        path = os.path.join(self.dir, "captive-portal.zip")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("<html>sign in to the wifi</html>")
        with self.assertRaises(OSError) as caught:
            updater.stage_release(path, os.path.join(self.dir, "staged"))
        self.assertIn("not a zip archive", str(caught.exception))

    def test_a_flat_archive_works_too(self):
        """An uploaded release asset need not wrap itself in a folder;
        only GitHub's generated zipball does."""
        staged = updater.stage_release(
            self._release_zip(root="", extras=False),
            os.path.join(self.dir, "staged"))
        self.assertEqual(sorted(updater.INSTALL_ENTRIES),
                         sorted(os.listdir(staged)))

    def test_the_staged_tree_swaps_in_and_the_old_one_is_kept(self):
        """End to end, which is the thing that had never run."""
        install = os.path.join(self.dir, "install")
        os.makedirs(os.path.join(install, "scripts"))
        with open(os.path.join(install, "scripts", "old.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write("the version being replaced")

        staged = updater.stage_release(self._release_zip(),
                                       os.path.join(self.dir, "staged"))
        backup = updater.apply_update(staged, install)

        self.assertTrue(
            os.path.exists(os.path.join(install, "scripts", "marker.txt")),
            "the release did not land in the install")
        self.assertTrue(
            os.path.exists(os.path.join(backup, "scripts", "old.txt")),
            "the previous install was not kept, so a bad release cannot "
            "be undone")

    def test_the_install_entries_match_the_ship_script(self):
        """Two homes for one list, so a source-derived guard rather than
        a promise: `sync-install.sh` is what actually builds an install,
        and this list is what an update writes into one."""
        # Five dirnames to the repo root, the spelling test_keyed_store
        # already uses to read tools/library-audit.py.
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        script = os.path.join(root, "tools", "sync-install.sh")
        with open(script, encoding="utf-8") as handle:
            text = handle.read()
        for entry in updater.INSTALL_ENTRIES:
            self.assertIn(
                '"$install/%s"' % entry, text,
                "%s is staged by the updater and not placed by "
                "sync-install.sh - the two disagree about what an "
                "install is" % entry)


if __name__ == "__main__":
    unittest.main()
