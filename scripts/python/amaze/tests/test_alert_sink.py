"""The sinks that SPEAK: `alert` once per condition, `refuse` once per gesture. ▸o/debug-engine ▸p/refusal-sink"""

import ast
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou                                                # noqa: E402
from PySide6 import QtCore                                # noqa: E402

from amaze.core import debug                             # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401


class AlertIsOncePerConditionTest(unittest.TestCase):
    """A condition inside a loop must interrupt ONCE."""

    def setUp(self):
        self._shown = []
        real = debug.alert    # captured through the headless print fallback rather than by mocking hou
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
        """A per-file message must still aggregate on the KEY, not the text."""
        shown = self._count(
            ("could not save icon a.png", "icons-not-saved"),
            ("could not save icon b.png", "icons-not-saved"),
            ("could not save icon c.png", "icons-not-saved"),
        )
        self.assertEqual(1, shown,
                         "a per-file message defeated the aggregation")

    def test_a_different_condition_is_not_suppressed(self):
        self.assertTrue(debug.alert("icons", key="icons-not-saved"))
        self.assertFalse(debug.alert("icons", key="icons-not-saved"))
        self.assertTrue(
            debug.alert("gradients", key="gradients-unreadable"),
            "a second, unrelated condition was suppressed by the first")

    def test_the_key_defaults_to_the_message(self):
        self.assertTrue(debug.alert("one exact sentence"))
        self.assertFalse(debug.alert("one exact sentence"))

    def test_it_is_recorded_even_when_it_does_not_show(self):
        """Every occurrence reaches the log, which is how "rare" is verified later."""
        debug.configure(True, debug.log_path())
        self.addCleanup(debug.configure, False, debug.log_path())
        before = os.path.getsize(debug.log_path())
        for _ in range(5):
            debug.alert("repeats", key="repeat-me")
        self.assertGreater(
            os.path.getsize(debug.log_path()), before,
            "suppressed alerts were not recorded, so the log cannot say "
            "how often the condition fired")


class RefuseIsTheGestureSinkTest(unittest.TestCase):
    """`debug.refuse`: bad aim to the status line, damage to a dialog. ▸p/refusal-sink"""

    def setUp(self):
        self.said = []
        self.shown = []
        self.printed = []

    def _ui(self):
        """Both calls, so a wrong branch is a wrong list and not an AttributeError reading as a crash."""
        return types.SimpleNamespace(
            setStatusMessage=lambda text, *a, **k: self.said.append(text),
            displayMessage=lambda text, *a, **k: self.shown.append(text),
        )

    def _fire_deferred(self, singleShot):
        """Run what the dialog branch parked."""
        for call in singleShot.call_args_list:
            call.args[1]()

    def test_bad_aim_goes_to_the_status_line(self):
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            debug.refuse("that node has no file parameter")
        self.assertEqual([], self.shown,
                         "a wrong-target refusal opened a dialog")
        self.assertEqual(1, len(self.said))
        self.assertIn("that node has no file parameter", self.said[0])

    def test_the_status_line_names_the_app(self):
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            debug.refuse("no ramp here")
        self.assertTrue(self.said[0].startswith("Amaze: "),
                        "the status line does not say who is speaking: %r"
                        % self.said[0])

    def test_damage_opens_a_dialog_instead(self):
        with mock.patch.object(hou, "ui", self._ui(), create=True), \
                mock.patch.object(QtCore.QTimer, "singleShot") as later:
            debug.refuse(debug.Damage('"Rust": asset file is missing.'))
            self._fire_deferred(later)
        self.assertEqual([], self.said,
                         "library damage went to the status line, which "
                         "the next write erases")
        self.assertEqual(['"Rust": asset file is missing.'], self.shown)

    def test_the_dialog_is_DEFERRED_past_the_pending_release_click(self):
        with mock.patch.object(hou, "ui", self._ui(), create=True), \
                mock.patch.object(QtCore.QTimer, "singleShot") as later:
            debug.refuse(debug.Damage("gone"))
            self.assertEqual(
                [], self.shown,
                "the dialog opened INSIDE the release handler, where it "
                "phantom-accepts the drag's own click")
            self.assertEqual(1, later.call_count)
            self._fire_deferred(later)
        self.assertEqual(["gone"], self.shown)

    def test_a_refusal_REPEATS_where_an_alert_would_not(self):
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            for _ in range(3):
                debug.refuse("that node has no file parameter")
        self.assertEqual(3, len(self.said),
                         "the refusal was de-duplicated like an alert, so "
                         "a repeated gesture looked like it landed")

    def test_it_holds_no_state_to_forget(self):
        """Red HERE when the sink grows state the blank slate would have to clear."""
        self.assertNotIn(
            "refus", str(debug._blank_slate.__doc__ or "").lower())
        for name in vars(debug):
            self.assertFalse(
                name.startswith("_refus"),
                "refuse() grew module state (%s) that the blank slate "
                "does not clear" % name)

    def test_headless_says_it_anyway_and_does_not_raise(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so the fallback is untested")
        with mock.patch("builtins.print", self.printed.append):
            shown = debug.refuse("no ramp here")
            damaged = debug.refuse(debug.Damage("gone"))
        self.assertTrue(shown and damaged,
                        "a headless refusal reported that it said nothing")
        self.assertEqual(2, len(self.printed))

    def test_formatting_a_marked_reason_LOSES_the_marking(self):
        """The mechanism's one trap, pinned as a known cost. ▸p/refusal-sink"""
        plain = "%s" % debug.Damage("gone")
        self.assertNotIsInstance(plain, debug.Damage)
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            debug.refuse(plain)
        self.assertEqual([], self.shown)
        self.assertEqual(1, len(self.said))

    def test_a_marked_reason_is_still_an_ordinary_string(self):
        marked = debug.Damage("gone")
        self.assertEqual("gone", marked)
        self.assertTrue(marked)
        self.assertIn("one", marked)
        self.assertEqual("gone", str(marked))


class TheDamageDoorMarksItsRefusalsTest(unittest.TestCase):
    """Every literal refusal the import door authors, classified. ▸p/refusal-sink ▸p/source-derived-tests"""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DOORS = ("_payload_or_refusal", "_import_asset_to_scene_inner",
             "_import_cop_asset_inner")

    DAMAGE = {    # opening words -> is the LIBRARY broken? A forwarded reason (a bare name) is absent: it keeps its origin's marking
        '"%s": asset file is missing on disk.': True,
        '"%s" cannot be imported: its id is not a usable file': True,
        '"%s" cannot be imported: its files resolve to': True,
        '"%s" cannot be imported: its material file is': True,
        '"%s" cannot be imported: its material file could': True,
        '"%s" has an unrecognised renderer': True,
        '"%s": failed to load into': True,
        '"%s": failed to load the saved network': True,
        '"%s" needs the "%s" node type, which is not': False,
        '"%s" could not be imported - a node type in it is': False,
        '"%s" holds %s nodes and a %s network cannot hold': False,
        '"%s" was loaded but could not be placed': False,
        '"%s": could not create a %s node in the current': False,
        "cannot import here: %s": False,
    }

    @staticmethod
    def _sentence(expr):
        """The literal a refusal is built from, or "" when it forwards one."""
        while isinstance(expr, ast.BinOp):
            expr = expr.left
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        return ""

    def _authored_refusals(self):
        """{sentence: marked} for every literal refusal the doors return."""
        with open(os.path.join(self.ROOT, "render", "nodes.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = {}
        for func in ast.walk(tree):
            if not (isinstance(func, ast.FunctionDef)
                    and func.name in self.DOORS):
                continue
            for node in ast.walk(func):
                if not (isinstance(node, ast.Return)
                        and isinstance(node.value, ast.Tuple)
                        and len(node.value.elts) >= 2):
                    continue
                payload = node.value.elts[1]
                marked = (isinstance(payload, ast.Call)
                          and isinstance(payload.func, ast.Attribute)
                          and payload.func.attr == "Damage")
                inner = payload.args[0] if marked else payload
                sentence = self._sentence(inner)
                if sentence:
                    found[sentence] = marked
        return found

    def test_the_doors_still_author_the_sentences_this_pins(self):
        """Red, never vacuous, when a sentence is reworded or moved."""
        found = self._authored_refusals()
        missing = [opening for opening in self.DAMAGE
                   if not any(s.startswith(opening) for s in found)]
        self.assertEqual(
            [], missing,
            "refusal(s) this test classifies are no longer returned by %s "
            "- re-key them in the same commit that moved them, never drop "
            "the entry:\n  %s" % (", ".join(self.DOORS),
                                  "\n  ".join(missing)))

    def test_each_sentence_is_marked_exactly_as_its_severity_says(self):
        wrong = []
        for sentence, marked in sorted(self._authored_refusals().items()):
            for opening, damage in self.DAMAGE.items():
                if sentence.startswith(opening):
                    if marked != damage:
                        wrong.append(
                            "%s: marked=%s, should be %s"
                            % (sentence[:60], marked, damage))
                    break
            else:
                wrong.append("%s: NEW refusal, classify it here"
                             % sentence[:60])
        self.assertEqual(
            [], wrong,
            "the import door's severity split has drifted - a damage "
            "sentence left unmarked reaches the user as a status line "
            "the next write erases, and a bad-aim sentence marked opens "
            "a dialog mid-gesture:\n  " + "\n  ".join(wrong))


class TheTenSitesAreConvertedTest(unittest.TestCase):
    """Source-derived: a print left on one of the ten is silent on Windows. ▸o/debug-engine"""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    EXPECTED = {    # file -> conditions it must raise; an EMPTY tuple means the condition moved to the keyed-store registry and the test below asserts it there - dropping the entry goes VACUOUS ▸p/source-derived-tests
        os.path.join("core", "gradient_library.py"): (
            "colors-not-saved",),    # the trailing comma is load-bearing: a bare string is walked one CHARACTER at a time
        os.path.join("core", "database.py"): ("unreadable-",),
        os.path.join("core", "tile_icons.py"): ("icons-not-saved",),
        os.path.join("core", "notes.py"): (),
        os.path.join("core", "keyed_store.py"): (),
        os.path.join("core", "matx_sources.py"): (
            "online-unsafe-archive-paths",),
    }

    def test_the_side_tables_conditions_moved_to_the_registry(self):
        """The stores declare their own sentences, so no `key="..."` literal remains to grep."""
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
        settings = keyed_store.store_for(keyed_store.SETTINGS)    # machine-local, so the loop skips it; EXPECTED can no longer see it either
        self.assertEqual("prefs-unreadable", settings.alert_key)
        self.assertIn("Repair tool", settings.unreadable_alert)

        source = open(os.path.join(self.ROOT, "core", "keyed_store.py"),
                      encoding="utf-8").read()
        self.assertIn(
            "key=spec.alert_key", source,
            "the engine raises the stores' alerts some other way, so "
            "the declared keys are decoration")

        speaks = {spec.filename for spec in keyed_store.stores()
                  if spec.denied_alert}    # the whole SET, because an omission and a deliberate silence read identically in a registry
        self.assertEqual(
            {"notes.json", "icons.json", "prefs.json", "settings.json"},
            speaks,
            "the stores that report a denied write changed - a comment, "
            "a tile icon, a shared setting and a preference stay on "
            "screen looking saved, so nothing but this tells the user; "
            "a location and a favourite are derived from their store "
            "and simply do not appear")
        self.assertIn(
            "if spec.denied_alert:", source,
            "the engine no longer raises the declared denial, so those "
            "sentences are decoration")

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
        """A work-affecting condition that prints says nothing on Windows."""
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
