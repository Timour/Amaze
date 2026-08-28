"""The restore drill - the real `tools/restore.py` driven against a COPY of the real library through the failure shapes that happen, because a restore nobody has rehearsed is a belief rather than a capability. NEVER touches the live library. ▸archive/test_restore_drill.py"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
RESTORE = os.path.join(REPO, "tools", "restore.py")

from amaze.tests import test_support             # noqa: E402


PYTHON = shutil.which("python3") or sys.executable


def _run(*args):
    # CLEAN: hython's PYTHONHOME/PYTHONPATH would give the child Houdini's stdlib.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH")}
    return subprocess.run([PYTHON, RESTORE] + list(args),
                          capture_output=True, text=True, env=env)


class TestRestoreDrill(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_drill_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "library.json")
        self.good = {"assets": [{"id": "a%d" % i, "name": "mat_%d" % i}
                                for i in range(500)], "tags": []},
        self.good = self.good[0]
        self._write(self.target, self.good)
        for tier, count in (("bak-1", 500), ("bak-2", 498), ("bak-3", 495),
                            ("bak-first", 495)):
            self._write(self.target + "." + tier,
                        {"assets": self.good["assets"][:count], "tags": []})

    def _write(self, path, data):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _assets(self, path=None):
        # utf-8-sig, like the app and the tool - a restore keeps its bytes.
        with open(path or self.target, encoding="utf-8-sig") as handle:
            return len(json.load(handle)["assets"])

    # -- the failure shapes that actually happen ------------------------

    def test_truncated_write_restores_from_bak1(self):
        """A write interrupted mid-flight leaves valid-looking bytes that are not valid json."""
        with open(self.target, "r+", encoding="utf-8") as handle:
            handle.truncate(5000)
        with self.assertRaises(ValueError):
            self._assets()
        result = _run("restore", "--allow-loss", self.target, "bak-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._assets(), 500)

    def test_corrupt_file_restores_and_is_itself_reversible(self):
        self._write_raw("{ not json at all")
        result = _run("restore", "--allow-loss", self.target, "bak-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._assets(), 498)
        # The name read from the line a USER would read.
        undo = self._undo_named_in(result.stdout)
        self.assertTrue(os.path.exists(undo))
        with open(undo, encoding="utf-8") as handle:
            self.assertEqual(
                "{ not json at all", handle.read(),
                "the undo copy is not the state that was replaced, so "
                "the restore is not actually reversible")

    def _undo_named_in(self, stdout):
        """The undo copy read out of the restore's OWN output, so a name printed but not written - or written but not printed - fails here."""
        lines = [line for line in stdout.splitlines()
                 if line.startswith("current state saved to ")]
        self.assertEqual(1, len(lines),
                         "the restore did not say where it saved the "
                         "current state:\n%s" % stdout)
        return os.path.join(self.tmp, lines[0].rsplit(None, 1)[-1])

    def test_the_undo_is_restorable_and_the_swap_goes_both_ways(self):
        """THE UNDO IS DRIVEN, never merely inspected - a preserved copy is not a restorable one, and checking only its bytes hid a restore that overwrote its own source."""
        self.assertEqual(500, self._assets(), "premise")
        first = _run("restore", "--allow-loss", self.target, "bak-3")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(495, self._assets())
        undo = self._undo_named_in(first.stdout)
        undo_tier = os.path.basename(undo)[len("library.json."):]

        listed = _run("list", self.target)
        self.assertIn(undo_tier, listed.stdout,
                      "the copy of the state that was replaced is not even "
                      "listed, so nobody can find the undo the tool says "
                      "it made")

        undone = _run("restore", "--allow-loss", self.target, undo_tier)
        self.assertEqual(undone.returncode, 0, undone.stderr)
        self.assertEqual(
            500, self._assets(),
            "the undo restored 495 - the state it was meant to bring back "
            "was overwritten before it was read")
        self.assertEqual(
            500, self._assets(undo),
            "restoring the undo copy consumed it, so the swap is a "
            "one-way door with two names")

    def test_a_second_restore_does_not_delete_the_first_ones_undo(self):
        """Two restores in a row must leave the starting state somewhere on disk - a shared undo name makes the second one a delete."""
        self.assertEqual(500, self._assets(), "premise")
        first = _run("restore", "--allow-loss", self.target, "bak-3")       # 495
        self.assertEqual(first.returncode, 0, first.stderr)
        second = _run("restore", "--allow-loss", self.target, "bak-2")      # 498
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(498, self._assets())
        first_undo = self._undo_named_in(first.stdout)
        second_undo = self._undo_named_in(second.stdout)
        self.assertNotEqual(first_undo, second_undo,
                            "two restores shared one undo name")
        self.assertEqual(
            500, self._assets(first_undo),
            "the pre-first-restore state is nowhere on disk - the second "
            "restore deleted what the first one saved")
        self.assertEqual(495, self._assets(second_undo))

    def test_a_snapshot_with_a_byte_order_mark_is_still_restorable(self):
        """THE TOOL MUST AGREE WITH THE APP ABOUT WHAT IS READABLE, or the recovery tool refuses the one shape the app already filed as healthy."""
        with open(self.target + ".bak-1", "w", encoding="utf-8-sig") as handle:
            json.dump({"assets": self.good["assets"][:497], "tags": []},
                      handle)
        with open(self.target + ".bak-1", "rb") as handle:
            self.assertEqual(b"\xef\xbb\xbf", handle.read(3),
                             "premise: the snapshot must really carry a BOM")
        listed = _run("list", self.target)
        self.assertIn(
            "497 assets", listed.stdout,
            "a byte-order mark made a healthy snapshot list as unreadable, "
            "so nobody would try to restore it in the first place")
        self._write_raw("{ not json at all")
        result = _run("restore", "--allow-loss", self.target, "bak-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(497, self._assets(),
                         "the BOM'd snapshot was refused, so the recovery "
                         "the app's own backup made is unusable")

    def test_deleted_index_restores_from_the_immutable_copy(self):
        """The rolling tiers age a good state out; `.bak-first` never rotates, which is why it exists."""
        os.remove(self.target)
        result = _run("restore", "--allow-loss", self.target, "bak-first")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._assets(), 495)

    def test_half_synced_file_is_refused_not_restored(self):
        """A cloud client can truncate the SNAPSHOT, and restoring garbage over a live index turns one problem into two."""
        with open(self.target + ".bak-1", "r+", encoding="utf-8") as handle:
            handle.truncate(120)
        result = _run("restore", "--allow-loss", self.target, "bak-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing", result.stderr.lower())
        self.assertEqual(self._assets(), 500, "the good file was overwritten")

    def test_list_reports_what_each_snapshot_holds(self):
        result = _run("list", self.target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("500 assets", result.stdout)
        self.assertIn("bak-first", result.stdout)

    def test_missing_tier_fails_cleanly(self):
        result = _run("restore", "--allow-loss", self.target, "bak-9")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._assets(), 500)

    def _write_raw(self, text):
        with open(self.target, "w", encoding="utf-8") as handle:
            handle.write(text)


class TestDrillAgainstRealSnapshots(unittest.TestCase):
    """The same drill against a COPY of the live library, so it runs on the real file's real snapshots."""

    def test_live_library_snapshots_are_restorable(self):
        prefs = test_support.live_library_to_rehearse_on(self)
        live = os.path.join(prefs.dir, "library.json")
        tmp = tempfile.mkdtemp(prefix="amaze_drill_live_")
        self.addCleanup(shutil.rmtree, tmp, True)
        target = os.path.join(tmp, "library.json")
        shutil.copy2(live, target)
        tiers = []
        for tier in ("bak-1", "bak-2", "bak-3", "bak-first"):
            source = live + "." + tier
            if os.path.exists(source):
                shutil.copy2(source, target + "." + tier)
                tiers.append(tier)
        self.assertTrue(tiers, "the live library has no snapshots at all")

        with open(target, "w", encoding="utf-8") as handle:
            handle.write("")          # the disaster
        for tier in tiers:
            result = _run("restore", "--allow-loss", target, tier)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(target, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertGreater(len(data.get("assets", [])), 0,
                               "%s restored an empty library" % tier)


class TestUnreadableSettingsArePreserved(unittest.TestCase):
    """An unparseable `settings.json` must SURVIVE the session: `load()` returning False leaves pure defaults and the panel opens anyway, so an unconditional save overwrites the real settings with them."""

    def setUp(self):
        from amaze.prefs import prefs as prefs_mod
        from amaze.helpers import hostos

        self.prefs_mod = prefs_mod
        self.hostos = hostos
        self.home = tempfile.mkdtemp(prefix="amaze_unreadable_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.settings = os.path.join(self.home, "settings.json")
        # snapshot_before_write is once per session per PATH, and its set outlives a test.
        hostos._session_snapshots.pop(self.settings, None)
        self.addCleanup(hostos._session_snapshots.pop, self.settings, None)

    def _prefs(self):
        p = self.prefs_mod.Prefs()
        p.path = self.home
        return p

    def _write_real_settings(self):
        p = self._prefs()
        p.dir = os.path.join(self.home, "library") + os.sep
        p._file_folders = ["/Volumes/Tex/wood", "/Volumes/Tex/metal"]
        p.save()
        with open(self.settings, encoding="utf-8") as handle:
            return handle.read()

    def test_a_truncated_settings_file_is_kept_before_anything_saves(self):
        raw = self._write_real_settings()
        truncated = raw[:len(raw) // 2]
        with open(self.settings, "w", encoding="utf-8") as handle:
            handle.write(truncated)

        loaded = self._prefs()
        self.assertFalse(loaded.load(), "a truncated file should not load")

        kept = self.settings + ".unreadable"
        self.assertTrue(
            os.path.exists(kept),
            "the unreadable settings file was not preserved - the next "
            "save writes defaults over it and the data is gone")
        with open(kept, encoding="utf-8") as handle:
            self.assertEqual(
                truncated, handle.read(),
                "the preserved copy is not the file we failed to read")

    def test_the_preserved_copy_is_never_overwritten(self):
        """A second failed load must not replace the original evidence with an already-defaulted rewrite."""
        raw = self._write_real_settings()
        truncated = raw[:len(raw) // 2]
        with open(self.settings, "w", encoding="utf-8") as handle:
            handle.write(truncated)
        self._prefs().load()

        with open(self.settings, "w", encoding="utf-8") as handle:
            handle.write("{ later garbage")
        self._prefs().load()

        with open(self.settings + ".unreadable", encoding="utf-8") as handle:
            self.assertEqual(
                truncated, handle.read(),
                "the second failure overwrote the first preserved copy")

    def test_a_first_run_preserves_nothing(self):
        """No settings.json yet is not a corruption."""
        self.assertFalse(self._prefs().load())
        self.assertFalse(
            os.path.exists(self.settings + ".unreadable"),
            "a first run left a spurious .unreadable file")

    def test_a_file_created_this_session_still_gets_a_snapshot(self):
        """Marking a path done BEFORE checking it exists burns the once-per-session marker on the save that CREATES the file, leaving every later save unprotected."""
        self._write_real_settings()          # creates the file
        first = self._prefs()
        first.load()
        first._file_folders = ["/Volumes/Tex/changed"]
        first.save()                          # the first save over a real file

        self.assertTrue(
            os.path.exists(self.settings + ".bak-first"),
            "no restore point was taken for a settings.json created "
            "earlier in the same session")


class PrefsValidationTest(unittest.TestCase):
    """`load()` must go through the SETTERS that validate these tokens - assigning straight onto the attributes leaves an invalid value in memory, and the combos then display something other than what is stored."""

    def setUp(self):
        from amaze.prefs import prefs as prefs_mod
        import json

        self.json = json
        self.prefs_mod = prefs_mod
        self.home = tempfile.mkdtemp(prefix="amaze_validate_")
        self.addCleanup(shutil.rmtree, self.home, True)

    def _load_with(self, **values):
        path = os.path.join(self.home, "settings.json")
        base = self.prefs_mod.Prefs()
        base.path = self.home
        base.save()
        with open(path, encoding="utf-8") as handle:
            data = self.json.load(handle)
        data.update(values)
        with open(path, "w", encoding="utf-8") as handle:
            self.json.dump(data, handle)
        loaded = self.prefs_mod.Prefs()
        loaded.path = self.home
        loaded.load()
        return loaded

    def test_an_invalid_line_weight_is_coerced(self):
        loaded = self._load_with(icon_line_weight="bold")
        self.assertIn(
            loaded.icon_line_weight, ("template", "feather"),
            "an invalid token survived load(), so the dialog shows one "
            "value while preferences hold another")

    def test_a_valid_value_is_preserved(self):
        loaded = self._load_with(icon_line_weight="feather")
        self.assertEqual("feather", loaded.icon_line_weight)


class ARestoreThatLosesRecordsMustBeMeantTest(unittest.TestCase):
    """A snapshot that PARSES is not one worth restoring - a bare `[]` over a full library exits 0 with no warning, which is the tool doing the damage it undoes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_loss_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "library.json")
        with open(self.target, "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"id": "a%d" % i} for i in range(50)],
                       "tags": []}, fh)
        with open(self.target + ".bak-1", "w", encoding="utf-8") as fh:
            json.dump({"assets": [], "tags": []}, fh)

    def test_an_empty_snapshot_is_refused_without_the_flag(self):
        result = _run("restore", self.target, "bak-1")
        self.assertEqual(1, result.returncode,
                         "an empty snapshot restored over 50 records "
                         "with exit code 0: " + result.stdout)
        self.assertIn("would lose 50", result.stderr,
                      "the refusal does not name what would be lost")
        with open(self.target, encoding="utf-8") as fh:
            self.assertEqual(50, len(json.load(fh)["assets"]),
                             "the refusal still modified the file")

    def test_the_flag_makes_it_deliberate(self):
        result = _run("restore", "--allow-loss", self.target, "bak-1")
        self.assertEqual(0, result.returncode, result.stderr)
        with open(self.target, encoding="utf-8") as fh:
            self.assertEqual(0, len(json.load(fh)["assets"]))

    def test_a_stranded_asset_is_named_on_the_way_out(self):
        result = _run("restore", "--allow-loss", self.target, "bak-1")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("a0", result.stdout,
                      "records stranded by the restore are not named - "
                      "the next Clean Library makes the discovery instead")


class TheUndoFamilyIsBoundedTest(unittest.TestCase):
    """Unique undo names trade overwriting for accumulation, so past the newest N they MOVE to the machine-local quarantine - never deleted, each holds a state that exists nowhere else."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO, "scripts", "python"))
        self.tmp = tempfile.mkdtemp(prefix="amaze_undo_bound_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "library.json")
        with open(self.target, "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"id": "a"}], "tags": []}, fh)
        self.config = tempfile.mkdtemp(prefix="amaze_undo_cfg_")
        self.addCleanup(shutil.rmtree, self.config, True)
        from amaze.helpers import hostos
        real = hostos.config_root
        hostos.config_root = lambda: self.config
        self.addCleanup(setattr, hostos, "config_root", real)

    def _mint(self, count):
        from amaze.helpers import restore as restore_lib
        for i in range(count):
            name = "%s.%s-20260701-%06d" % (self.target,
                                            restore_lib.UNDO_TIER, i)
            with open(name, "w", encoding="utf-8") as fh:
                json.dump({"assets": [], "tags": []}, fh)

    def _family(self):
        from amaze.helpers import restore as restore_lib
        prefix = "library.json." + restore_lib.UNDO_TIER + "-"
        return sorted(n for n in os.listdir(self.tmp)
                      if n.startswith(prefix))

    def test_the_family_stays_at_the_cap(self):
        from amaze.helpers import restore as restore_lib
        self._mint(restore_lib.KEEP_UNDO_COPIES + 3)
        retired = restore_lib._retire_old_undo_copies(self.target)
        self.assertEqual(3, len(retired))
        self.assertEqual(restore_lib.KEEP_UNDO_COPIES,
                         len(self._family()),
                         "the undo family is not bounded - it grows in a "
                         "synced folder forever")

    def test_retired_copies_are_in_quarantine_not_gone(self):
        from amaze.core import library as library_mod
        from amaze.helpers import restore as restore_lib
        self._mint(restore_lib.KEEP_UNDO_COPIES + 2)
        retired = restore_lib._retire_old_undo_copies(self.target)
        self.assertEqual(2, len(retired))
        root = os.path.join(
            __import__("amaze.helpers.hostos", fromlist=["h"])
            .history_root(self.target), library_mod.QUARANTINE_PREFIX)
        held = []
        for folder, _dirs, files in os.walk(root):
            held.extend(files)
        for name in retired:
            self.assertIn(name, held,
                          "a retired undo copy is nowhere - it held a "
                          "state that existed in no other file")

    def test_the_oldest_go_first(self):
        from amaze.helpers import restore as restore_lib
        self._mint(restore_lib.KEEP_UNDO_COPIES + 1)
        retired = restore_lib._retire_old_undo_copies(self.target)
        self.assertTrue(retired[0].endswith("-000000"),
                        "retirement did not take the oldest state first")


class PrefsLoadNeverRaisesTest(unittest.TestCase):
    """An exception in `load()` kills the panel during construction with no interface and no message, because `panel.py` re-raises."""

    def _prefs_with(self, payload):
        import json
        from amaze.prefs import prefs as prefs_mod
        folder = tempfile.mkdtemp(prefix="amaze_prefs_raise_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with open(os.path.join(folder, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(payload, handle)
        p = prefs_mod.Prefs()
        p.path = folder
        return p

    def test_malformed_values_do_not_raise(self):
        for key, bad in (
            ("enabled_sections", None), ("enabled_sections", "material"),
            ("enabled_sections", 3), ("enabled_sections", {"material": 1}),
            ("file_folders", None), ("file_folders", 5),
            ("file_favorites", True), ("file_folders", "a/b"),
            ("directory", None), ("directory", {}), ("directory", []),
            # TRUTHY non-strings reach os.path.exists; falsy ones short-circuit.
            ("directory", {"a": 1}), ("directory", [1]), ("directory", 7),
        ):
            with self.subTest(key=key, value=bad):
                prefs = self._prefs_with({key: bad})
                try:
                    prefs.load()
                except Exception as exc:            # noqa: BLE001
                    self.fail("load() raised on %s=%r: %s: %s"
                              % (key, bad, type(exc).__name__, exc))

    def test_a_string_does_not_decompose_into_characters(self):
        prefs = self._prefs_with({"file_folders": "a/b"})
        prefs.load()
        self.assertEqual(
            [], list(prefs.file_folders),
            "a bare string was iterated into single characters, which "
            "reaches the sidebar as bogus folders")

    def test_a_byte_order_mark_does_not_cost_the_session(self):
        """EVERY reader of `settings.json` takes utf-8-sig, or one file gets two verdicts - the panel opens empty and refuses saves while the snapshot machinery files the same bytes as known-good."""
        import codecs
        import json as json_mod
        from amaze.prefs import prefs as prefs_mod
        folder = tempfile.mkdtemp(prefix="amaze_prefs_bom_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with open(os.path.join(folder, "settings.json"), "wb") as handle:
            handle.write(codecs.BOM_UTF8)
            handle.write(json_mod.dumps(
                {"ram_cache_mb": 321}).encode("utf-8"))
        prefs = prefs_mod.Prefs()
        prefs.path = folder
        prefs.load()
        self.assertEqual(
            321, prefs.ram_cache_mb,
            "three invisible bytes made settings.json unreadable - "
            "no library, every save refused for the session, while "
            "the backup tier reads the same bytes as healthy")


class PrefsRefusesToOverwriteTest(unittest.TestCase):
    """REFUSE OVER OVERWRITE, the clause settings.json was missing."""

    def _broken(self):
        from amaze.prefs import prefs as prefs_mod
        folder = tempfile.mkdtemp(prefix="amaze_prefs_broken_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "settings.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"directory": "/x", ')     # truncated
        p = prefs_mod.Prefs()
        p.path = folder
        return p, path

    def test_a_save_after_a_failed_load_is_refused(self):
        prefs, path = self._broken()
        prefs.load()
        before = open(path, encoding="utf-8").read()
        prefs.save()
        self.assertEqual(
            before, open(path, encoding="utf-8").read(),
            "defaults were written over a settings file we could not "
            "read - that is how 200 gradients became 1")

    def test_an_ordinary_save_still_works(self):
        from amaze.prefs import prefs as prefs_mod
        folder = tempfile.mkdtemp(prefix="amaze_prefs_ok_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        p = prefs_mod.Prefs()
        p.path = folder
        p.load()
        p.save()
        self.assertTrue(
            os.path.exists(os.path.join(folder, "settings.json")),
            "the refusal latched on a perfectly good load")


if __name__ == "__main__":
    unittest.main()
