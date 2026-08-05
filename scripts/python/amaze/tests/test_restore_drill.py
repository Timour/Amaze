"""The restore drill: prove the snapshots can actually be put back.

The backup system has saved this project's data twice, but a restore
had never been rehearsed end to end - which means it was a belief, not
a capability. These tests run the real tool (tools/restore.py) against
a COPY of the real library, through the failure shapes that actually
happen: a truncated write, corrupt json, a deleted index, and a
half-synced cloud file.

Never touches the live library: everything runs in a temp copy.
"""

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

# tests/ -> amaze/ -> python/ -> scripts/ -> repo root: FIVE levels.
# (Got this wrong once already today in the other direction - counting
# them out beats eyeballing nested dirname calls.)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
RESTORE = os.path.join(REPO, "tools", "restore.py")


#: restore.py is pure stdlib on purpose - a restore must work when
#: Houdini does not start. Driving it with the SYSTEM python keeps the
#: drill fast (hython costs ~10s of startup per call, which turned this
#: file into 72 seconds) and proves the no-Houdini claim at the same
#: time.
PYTHON = shutil.which("python3") or sys.executable


def _run(*args):
    return subprocess.run([PYTHON, RESTORE] + list(args),
                          capture_output=True, text=True)


class TestRestoreDrill(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_drill_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "library.json")
        # A realistic index plus the snapshot tiers the app maintains.
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
        # utf-8-sig, like the app and like the tool: a restored snapshot
        # keeps whatever bytes it had, byte-order mark included.
        with open(path or self.target, encoding="utf-8-sig") as handle:
            return len(json.load(handle)["assets"])

    # -- the failure shapes that actually happen ------------------------

    def test_truncated_write_restores_from_bak1(self):
        """A write interrupted mid-flight - the classic crash/power
        case - leaves valid-looking bytes that are not valid json."""
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
        # The corrupt state was preserved - a panic restore is undoable.
        # The tool names the copy it made (timestamped, one per restore),
        # so the drill reads the name from the same line a user would.
        undo = self._undo_named_in(result.stdout)
        self.assertTrue(os.path.exists(undo))
        # "The undo file exists" is not the claim worth making. What the
        # drill has to prove is that the bytes in it are the ones that
        # were on disk - a copy of the wrong thing, or a truncated copy,
        # looks identical to this test until it is read.
        with open(undo, encoding="utf-8") as handle:
            self.assertEqual(
                "{ not json at all", handle.read(),
                "the undo copy is not the state that was replaced, so "
                "the restore is not actually reversible")

    def _undo_named_in(self, stdout):
        """The undo copy a restore said it wrote, from its own output -
        the same sentence a user acts on, so a name printed but not
        written (or written but not printed) fails here."""
        lines = [line for line in stdout.splitlines()
                 if line.startswith("current state saved to ")]
        self.assertEqual(1, len(lines),
                         "the restore did not say where it saved the "
                         "current state:\n%s" % stdout)
        return os.path.join(self.tmp, lines[0].rsplit(None, 1)[-1])

    def test_the_undo_is_restorable_and_the_swap_goes_both_ways(self):
        """THE UNDO HAD TO BE DRIVEN, not merely inspected. A previous
        version of this drill stopped at "the undo copy holds the right
        bytes" and recorded the rest as a finding: the undo was a single
        fixed name and put_back wrote it BEFORE reading its source, so
        `restore <file> bak-before-restore` overwrote the undo with the
        state it was about to undo and then copied that over itself.
        Measured through this same CLI: 500 assets, restore bak-3 (495),
        undo -> still 495, and the 500-asset state gone from the folder.
        Two success messages, no error, five assets lost.

        A preserved copy is not a restorable one, and the dialogs that
        promise the undo are read by somebody who has just made a choice
        under pressure."""
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
        """The fixed-name defect, driven end to end through the CLI: two
        restores in a row must leave the starting state somewhere on
        disk. Before unique undo names, the second restore overwrote the
        only copy of it - two success messages, no error, data gone."""
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
        """THE TOOL MUST AGREE WITH THE APP ABOUT WHAT IS READABLE. The app
        now reads databases as utf-8-sig, so hostos.parses_as_json calls a
        BOM'd document healthy and snapshot_before_write copies it into the
        write-once .bak-first tier. Reading plain utf-8 here made that exact
        file the one this tool listed as NOT VALID JSON and refused to put
        back - the recovery tool declining the one shape that most needs
        recovering."""
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
        """The rolling tiers can age out a good state; bak-first never
        rotates, which is the whole reason it exists."""
        os.remove(self.target)
        result = _run("restore", "--allow-loss", self.target, "bak-first")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._assets(), 495)

    def test_half_synced_file_is_refused_not_restored(self):
        """A cloud client can leave a snapshot itself truncated.
        Restoring garbage over a live index would turn one problem into
        two - the tool must refuse."""
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
    """The same drill against a COPY of the live library - the rehearsal
    that matters, since it uses the real file's real snapshots."""

    def test_live_library_snapshots_are_restorable(self):
        from amaze.prefs import prefs as prefs_mod
        prefs = prefs_mod.Prefs()
        prefs.load()
        live = os.path.join(prefs.dir, "library.json")
        if not os.path.exists(live):
            self.skipTest("no live library on this machine")
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
    """A settings.json we cannot parse must survive the session.

    load() returning False leaves the object holding PURE DEFAULTS and
    the panel opens anyway - deliberate, so a bad settings file cannot
    cost the whole panel. But nothing downstream could tell "no settings
    yet" from "settings we failed to read", and save() is
    unconditional: opening Preferences and closing it was enough.

    Reproduced end to end before the fix - a truncated settings.json,
    then one save():

        before : folders=2 favs=1 accent=#ff8800
        after  : folders=0 favs=0 accent=#5d7abd   (defaults)

    and no recovery artifact at all, because snapshot_before_write is
    once-per-session and the marker had already been spent on a file
    that did not exist yet (fixed in hostos)."""

    def setUp(self):
        from amaze.prefs import prefs as prefs_mod
        from amaze.helpers import hostos

        self.prefs_mod = prefs_mod
        self.hostos = hostos
        self.home = tempfile.mkdtemp(prefix="amaze_unreadable_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.settings = os.path.join(self.home, "settings.json")
        # snapshot_before_write is once per session per PATH, and the
        # module-level set outlives a single test.
        hostos._session_snapshots.pop(self.settings, None)
        self.addCleanup(hostos._session_snapshots.pop, self.settings, None)

    def _prefs(self):
        p = self.prefs_mod.Prefs()
        p.path = self.home
        p.legacy_path = ""
        return p

    def _write_real_settings(self):
        p = self._prefs()
        p.dir = os.path.join(self.home, "library") + os.sep
        p._texture_folders = ["/Volumes/Tex/wood", "/Volumes/Tex/metal"]
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
        """A second failed load in the same session must not replace the
        original evidence with an already-defaulted rewrite."""
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
        """snapshot_before_write marked the path as done BEFORE checking
        the file existed, so the save that CREATES settings.json burned
        the once-per-session marker and every later save that session
        was unprotected."""
        self._write_real_settings()          # creates the file
        first = self._prefs()
        first.load()
        first._texture_folders = ["/Volumes/Tex/changed"]
        first.save()                          # the first save over a real file

        self.assertTrue(
            os.path.exists(self.settings + ".bak-first"),
            "no restore point was taken for a settings.json created "
            "earlier in the same session")


class PrefsValidationTest(unittest.TestCase):
    """load() must go through the setters that validate these tokens.

    It assigned straight onto the attributes, so a settings.json holding
    icon_line_weight="bold" (hand-edited, or written by a build that
    spelled it differently) stayed invalid in memory - and the
    Preferences combos, which fall back to index 0 on an unknown token,
    then DISPLAYED something different from what was stored."""

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
        base.legacy_path = ""
        base.save()
        with open(path, encoding="utf-8") as handle:
            data = self.json.load(handle)
        data.update(values)
        with open(path, "w", encoding="utf-8") as handle:
            self.json.dump(data, handle)
        loaded = self.prefs_mod.Prefs()
        loaded.path = self.home
        loaded.legacy_path = ""
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


class MigrationMarkerTest(unittest.TestCase):
    """The install migration is once, not "whenever the target is gone".

    The only guard was os.path.exists(target), so deleting
    settings.json to reset preferences - or restoring a backup that did
    not include it - made the next launch silently copy the
    pre-2026-07-27 install copy back, resurrecting a stale library path
    and stale favourites."""

    def setUp(self):
        from amaze.prefs import prefs as prefs_mod
        import json

        self.json = json
        self.prefs_mod = prefs_mod
        self.home = tempfile.mkdtemp(prefix="amaze_migrate_")
        self.legacy = tempfile.mkdtemp(prefix="amaze_legacy_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.addCleanup(shutil.rmtree, self.legacy, True)
        with open(os.path.join(self.legacy, "settings.json"), "w",
                  encoding="utf-8") as handle:
            self.json.dump({"directory": "/from/the/install"}, handle)

    def _open(self):
        prefs = self.prefs_mod.Prefs()
        prefs.path = self.home
        prefs.legacy_path = self.legacy
        prefs.load()
        return prefs

    def test_it_migrates_once(self):
        self._open()
        target = os.path.join(self.home, "settings.json")
        self.assertTrue(os.path.exists(target), "nothing was migrated")

    def test_deleting_settings_does_not_resurrect_the_install_copy(self):
        self._open()
        target = os.path.join(self.home, "settings.json")
        os.remove(target)                      # a deliberate reset
        self._open()
        self.assertFalse(
            os.path.exists(target),
            "the install copy was silently restored, bringing back a "
            "stale library path and stale favourites")


class ARestoreThatLosesRecordsMustBeMeantTest(unittest.TestCase):
    """cmd_restore validated only that the snapshot PARSES - a bare []
    restores over a 548-record library with exit code 0 and no warning,
    which is the tool doing the damage it exists to undo."""

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
    """Uniquifying the undo copies traded overwriting for accumulation:
    an unbounded family of timestamped files in a synced folder. Beyond
    the newest N they move to the machine-local quarantine - moved, not
    deleted, because each holds a state that exists nowhere else."""

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


if __name__ == "__main__":
    unittest.main()


class PrefsLoadNeverRaisesTest(unittest.TestCase):
    """load()'s own docstring: an exception here "would kill the panel
    during construction, with no interface and no message" - and
    panel.py re-raises. Four shapes did exactly that.
    """

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
            ("texture_folders", None), ("texture_folders", 5),
            ("geometry_folders", True), ("hip_folders", "a/b"),
            ("directory", None), ("directory", {}), ("directory", []),
            # TRUTHY non-strings are the ones that actually reach
            # os.path.exists - the falsy ones short-circuit, so a test
            # using only those proves nothing about the type guard.
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
        prefs = self._prefs_with({"hip_folders": "a/b"})
        prefs.load()
        self.assertEqual(
            [], list(prefs.hip_folders),
            "a bare string was iterated into single characters, which "
            "reaches the sidebar as bogus folders")


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
