"""Compiled files: what is stale, what is written, and the update and the panel that write them."""

import importlib.machinery
import os
import py_compile
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from amaze.helpers import bytecode
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _OneModule(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_bytecode_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.module = os.path.join(self.root, "pkg", "mod.py")
        test_support.write_text(self.module, "VALUE = 1\n")

    def _compile(self, mode):
        py_compile.compile(self.module, doraise=True, invalidation_mode=mode)


class StaleNamesWhatPythonWouldCompileTest(_OneModule):

    def test_an_uncompiled_file_is_stale(self):
        self.assertEqual([self.module], bytecode.stale(self.root))

    def test_a_hash_checked_compile_of_the_source_it_holds_is_current(self):
        self._compile(py_compile.PycInvalidationMode.CHECKED_HASH)
        self.assertEqual([], bytecode.stale(self.root))

    def test_a_timestamp_checked_compile_is_stale(self):
        """The kind Python writes itself, which a .py synced with an older mtime fools."""
        self._compile(py_compile.PycInvalidationMode.TIMESTAMP)
        self.assertEqual([self.module], bytecode.stale(self.root))

    def test_a_compile_of_an_older_source_is_stale(self):
        self._compile(py_compile.PycInvalidationMode.CHECKED_HASH)
        test_support.write_text(self.module, "VALUE = 2\n")
        self.assertEqual([self.module], bytecode.stale(self.root))

    def test_a_tests_folder_is_never_walked(self):
        test_support.write_text(os.path.join(self.root, "pkg", "tests", "test_mod.py"), "X = 1\n")
        self.assertEqual([self.module], bytecode.stale(self.root))


class CompileMissingTest(_OneModule):

    def test_what_it_writes_python_loads_without_compiling_the_source(self):
        self.assertEqual(1, bytecode.compile_missing(self.root))
        loader = importlib.machinery.SourceFileLoader("mod", self.module)
        with mock.patch.object(loader, "source_to_code",
                               side_effect=AssertionError("the source was compiled")):
            code = loader.get_code("mod")
        namespace = {}
        exec(code, namespace)
        self.assertEqual(1, namespace["VALUE"])

    def test_a_second_run_writes_nothing(self):
        bytecode.compile_missing(self.root)
        self.assertEqual(0, bytecode.compile_missing(self.root))

    def test_a_folder_it_cannot_write_is_skipped_before_compiling(self):
        with mock.patch.object(bytecode.os, "access", return_value=False), \
                mock.patch.object(py_compile, "compile") as compile_:
            self.assertEqual(0, bytecode.compile_missing(self.root))
        compile_.assert_not_called()

    def test_a_file_that_does_not_compile_is_skipped(self):
        test_support.write_text(os.path.join(self.root, "pkg", "broken.py"), "def (:\n")
        self.assertEqual(1, bytecode.compile_missing(self.root))

    def test_the_background_run_hands_back_what_it_wrote(self):
        written = []
        bytecode.compile_missing_in_background(self.root, written.append).join(30)
        self.assertEqual([1], written)


class AnUpdateArrivesCompiledTest(unittest.TestCase):
    """A release carries .py only, so the updater compiles it before the swap."""

    def test_every_module_of_an_installed_release_is_compiled(self):
        from amaze.core import updater

        work = tempfile.mkdtemp(prefix="amaze_bytecode_update_")
        self.addCleanup(shutil.rmtree, work, True)
        archive = os.path.join(work, "release.zip")
        with zipfile.ZipFile(archive, "w") as bundle:
            for entry in updater.INSTALL_ENTRIES:
                if entry.endswith(".xml"):
                    bundle.writestr("r/" + entry, "<menu/>")
                else:
                    bundle.writestr("r/%s/marker.txt" % entry, "from the release")
            bundle.writestr("r/scripts/python/amaze/mod.py", "VALUE = 1\n")
        install = os.path.join(work, "install")
        os.makedirs(install)

        def _download(url, into, digest="", size=0):
            os.makedirs(into, exist_ok=True)
            return shutil.copy(archive, os.path.join(into, "release.zip"))

        found = updater.Update(updater.NEWER, version="9.9.9",
                               url="https://example.invalid/r.zip")
        with mock.patch.object(updater, "download", side_effect=_download):
            updater.install(found, into=install)
        scripts = os.path.join(install, "scripts")
        self.assertTrue(os.path.isfile(os.path.join(scripts, "python", "amaze", "mod.py")))
        self.assertEqual([], bytecode.stale(scripts), "the update left modules uncompiled")


class TheFirstShowFillsInWhatIsMissingTest(unittest.TestCase):

    def _shown_twice(self, panel):
        with mock.patch.object(bytecode, "compile_missing_in_background") as fill:
            for _ in range(2):
                panel.show()
                for _ in range(5):
                    QtWidgets.QApplication.processEvents()
                panel.hide()
        return fill

    def test_the_first_show_starts_one_background_compile_of_the_package(self):
        import amaze
        from amaze.panel import panel as panel_mod

        panel = test_support.fixture_panel(self)
        with mock.patch.object(panel_mod.AmazePanel, "FILL_DELAY_MS", 0):
            fill = self._shown_twice(panel)
        self.assertEqual(1, fill.call_count, "the fill did not run once, on the first show")
        self.assertEqual(amaze.PACKAGE_ROOT, fill.call_args[0][0])

    def test_the_fill_waits_out_the_first_paint(self):
        """Measured: a fill during the first paint slowed it from about 90 ms to 310."""
        fill = self._shown_twice(test_support.fixture_panel(self))
        self.assertEqual(0, fill.call_count, "the fill ran while the first paint was still due")


if __name__ == "__main__":
    unittest.main()
