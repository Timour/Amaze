"""debug.alert - the third sink, and why the other two could not do it.

`event()` writes to the log only. `note()` prints - and on Windows it
returns BEFORE the print, while its log write is gated on Debug Mode. So
on Windows with Debug Mode off, `note()` says nothing anywhere. Routing
"your save did not happen" through it would have turned a visible
failure into a silent one on the exact platform the no-print rule exists
to protect. That is what `alert()` is for.

WHEN IT IS ALLOWED: rare AND important (settled 2026-07-30).
Ten print sites qualified, and they collapse to SIX conditions - four of
the ten sit inside loops (one icon per tile, one bad path per archive),
so ten naive dialogs would have been a dialog storm. The aggregation is
the part that fails silently if it breaks, so it is what these tests
pin.

The dialog itself is DEFERRED with QTimer.singleShot(0) and research.md
gives two independent reasons, either alone disqualifying: a modal
opened inside dropEvent phantom-accepts its default button from the
drag's own release click, and a native hou.ui dialog raised while a
modal QDialog is exec'd is invisible behind it - the nested
cross-toolkit modal loops crashed Houdini once, natively and log-silent.
"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import debug                             # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401


class AlertIsOncePerConditionTest(unittest.TestCase):
    """A condition inside a loop must interrupt ONCE."""

    def setUp(self):
        self._shown = []
        # alert() falls back to print when hou has no UI, which is the
        # headless case - capture that rather than mocking hou.
        real = debug.alert
        self.addCleanup(setattr, debug, "alert", real)
        self.addCleanup(debug._alerted.clear)
        debug._alerted.clear()

    def _count(self, *calls):
        shown = 0
        for message, key in calls:
            if debug.alert(message, key=key):
                shown += 1
        return shown

    def test_the_same_key_shows_once(self):
        shown = self._count(*[("could not save the icon", "icons-not-saved")
                              for _ in range(12)])
        self.assertEqual(1, shown,
                         "12 icons in a loop produced %d dialogs" % shown)

    def test_a_formatted_message_still_aggregates_via_the_key(self):
        """THE trap. The message differs every time (a filename, a count),
        so aggregation MUST key on the caller's key, not the text."""
        shown = self._count(
            ("could not save icon a.png", "icons-not-saved"),
            ("could not save icon b.png", "icons-not-saved"),
            ("could not save icon c.png", "icons-not-saved"),
        )
        self.assertEqual(1, shown,
                         "a per-file message defeated the aggregation")

    def test_a_different_condition_is_not_suppressed(self):
        """A noisy condition must never silence an unrelated one - the
        same rule the crash tier's flood guard follows."""
        self.assertTrue(debug.alert("icons", key="icons-not-saved"))
        self.assertFalse(debug.alert("icons", key="icons-not-saved"))
        self.assertTrue(
            debug.alert("gradients", key="gradients-unreadable"),
            "a second, unrelated condition was suppressed by the first")

    def test_the_key_defaults_to_the_message(self):
        self.assertTrue(debug.alert("one exact sentence"))
        self.assertFalse(debug.alert("one exact sentence"))

    def test_it_is_recorded_even_when_it_does_not_show(self):
        """The log must carry every occurrence, not just the first - the
        count is how "rare" gets verified later instead of assumed."""
        debug.configure(True, debug.log_path())
        self.addCleanup(debug.configure, False, debug.log_path())
        before = os.path.getsize(debug.log_path())
        for _ in range(5):
            debug.alert("repeats", key="repeat-me")
        self.assertGreater(
            os.path.getsize(debug.log_path()), before,
            "suppressed alerts were not recorded, so the log cannot say "
            "how often the condition fired")


class TheTenSitesAreConvertedTest(unittest.TestCase):
    """Source-derived. The ten sites were the whole point; a print left
    behind on one of them is silent on Windows, which is the bug."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    #: file -> the conditions it must raise
    EXPECTED = {
        os.path.join("core", "gradient_library.py"): (
            "gradients-unreadable", "gradients-changed-on-disk"),
        # The unreadable alert moved into the Keyed Store Engine on
        # 2026-08-03 - it is now ONE sentence per store, declared with
        # the store and raised by the engine that discovers the
        # condition. tile_icons keeps the one alert that is about the
        # user's own action rather than about the file.
        os.path.join("core", "tile_icons.py"): ("icons-not-saved",),
        os.path.join("core", "notes.py"): ("notes-not-saved",),
        os.path.join("core", "keyed_store.py"): (),
        # RE-KEYED 2026-08-09, in the same change that moved it.
        # `_preserve_unreadable` discovers this condition, and it left
        # `prefs.py` for `persistence.py` with the rest of the
        # save/load half. The detector follows the code, exactly as the
        # side tables' keys did above. Left pointing at `prefs.py` it
        # goes red for a move; dropping the entry instead would have
        # gone VACUOUS, which is worse.
        os.path.join("prefs", "persistence.py"): ("prefs-unreadable",),
        os.path.join("core", "matx_sources.py"): (
            "online-unsafe-archive-paths",),
    }

    def test_the_side_tables_conditions_moved_to_the_registry(self):
        """RE-KEYED 2026-08-03, in the same change that moved them.

        `notes-unreadable` and `icons-unreadable` used to be two
        `key="..."` literals in two modules. They are now ONE sentence
        per store, declared with the store in the Keyed Store Engine's
        registry and raised by the engine that discovers the condition -
        so a `key="..."` grep finds neither, and would have gone
        VACUOUS rather than red. A detector whose token has moved must
        be re-keyed in the same commit; nothing else reminds you."""
        from amaze.core import keyed_store

        for spec in keyed_store.stores():
            if not spec.in_library:
                continue
            self.assertTrue(
                spec.unreadable_alert,
                "%s has no sentence for the user when it cannot be "
                "read - the condition is the whole reason the store "
                "refuses to write" % spec.filename)
            self.assertTrue(spec.alert_key,
                            "%s raises its alert with no key, so it "
                            "cannot be de-duplicated" % spec.filename)
            self.assertIn(
                "Repair tool", spec.unreadable_alert,
                "%s tells the user it will not save over their work "
                "without saying how to get it back" % spec.filename)
        keys = {spec.alert_key for spec in keyed_store.stores()}
        self.assertIn("notes-unreadable", keys)
        self.assertIn("icons-unreadable", keys)

        source = open(os.path.join(self.ROOT, "core", "keyed_store.py"),
                      encoding="utf-8").read()
        self.assertIn(
            "key=spec.alert_key", source,
            "the engine raises the stores' alerts some other way, so "
            "the declared keys are decoration")

    def test_every_condition_is_raised_through_alert(self):
        missing = []
        for rel, keys in self.EXPECTED.items():
            with open(os.path.join(self.ROOT, rel), encoding="utf-8") as fh:
                src = fh.read()
            for key in keys:
                if 'key="%s"' % key not in src:
                    missing.append("%s: %s" % (rel, key))
        self.assertEqual([], missing,
                         "condition(s) no longer raised: %s" % missing)

    def test_none_of_them_kept_a_bare_print(self):
        """The failure this whole change exists to remove: a print on a
        path where the user's work was affected says nothing on Windows."""
        offenders = []
        for rel in self.EXPECTED:
            path = os.path.join(self.ROOT, rel)
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if not stripped.startswith("print("):
                        continue
                    if any(w in line.lower() for w in (
                            "not saving", "could not read your settings",
                            "disabled this session", "suspicious",
                            "could not save tile", "could not write the tile",
                    )):
                        offenders.append("%s:%d %s" % (rel, n, stripped[:60]))
        self.assertEqual(
            [], offenders,
            "a work-affecting condition still prints instead of "
            "alerting:\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
