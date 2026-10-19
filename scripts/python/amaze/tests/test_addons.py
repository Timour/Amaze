"""Add-on packages: the one writer, the refusing reader, the whole-folder installer, the carry."""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import addons, packages, updater          # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _node(label, kind, icon="icons/one.svg", needs=()):
    return {"label": label, "type": "Sop/example::%s::0.1" % kind,
            "file": "otls/example_%s.hda" % kind, "icon": icon,
            "description": "", "needs": list(needs)}


class _Workspace(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_addons_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.root = os.path.join(self.dir, "source")
        self.out = os.path.join(self.dir, "store")
        self.amaze = os.path.join(self.dir, "Amaze")
        os.makedirs(self.out)
        os.makedirs(self.amaze)

    def fields(self, version="1.2.3", nodes=None, **extra):
        made = {"name": "Example", "folder": "shapes", "version": version,
                "author": "Test Author", "houdini": "22.0.466", "houdini_min": "22.0",
                "changelog": "- A change.", "nodes": nodes or [_node("One", "one")]}
        made.update(extra)
        return made

    def package(self, files=None, version="1.2.3", **extra):
        files = files or {"otls/example_one.hda": "hda one", "icons/one.svg": "<svg/>"}
        for member, text in files.items():
            _write(os.path.join(self.root, *member.split("/")), text)
        return addons.write(self.out, self.fields(version, **extra), self.root, list(files))


class TheWriterTest(_Workspace):

    def test_a_written_package_reads_back_with_every_field(self):
        path = self.package(description="One line.")
        self.assertEqual("Example-1.2.3.amazepkg", os.path.basename(path))
        manifest = addons.read(path)
        self.assertEqual((packages.FORMAT, addons.KIND), (manifest["format"], manifest["kind"]))
        self.assertEqual(["icons/one.svg", "otls/example_one.hda"], manifest["files"])
        self.assertEqual(("Test Author", "22.0", "One line.", ""),
                         (manifest["author"], manifest["houdini_min"],
                          manifest["description"], manifest["nodes"][0]["description"]))

    def test_two_nodes_may_share_one_icon(self):
        files = {"otls/example_one.hda": "1", "otls/example_two.hda": "2", "icons/one.svg": "s"}
        nodes = [_node("One", "one"), _node("Two", "two", needs=["Sop/example::one::0.1"])]
        self.assertEqual(2, len(addons.read(self.package(files, nodes=nodes))["nodes"]))

    def test_a_member_passed_twice_is_written_once(self):
        _write(os.path.join(self.root, "otls", "example_one.hda"), "1")
        _write(os.path.join(self.root, "icons", "one.svg"), "s")
        path = addons.write(self.out, self.fields(), self.root,
                            ["otls/example_one.hda", "icons/one.svg", "icons/one.svg"])
        with zipfile.ZipFile(path) as bundle:
            self.assertEqual(1, bundle.namelist().count("icons/one.svg"))

    def test_every_problem_is_named_at_once(self):
        node = _node("One", "one")
        del node["description"]
        with self.assertRaises(packages.PackageError) as caught:
            self.package(version="1.2", nodes=[node], folder="elsewhere")
        for named in ("version '1.2' is not X.Y.Z", "no add-on folder 'elsewhere'",
                      "lacks description"):
            self.assertIn(named, str(caught.exception))

    def test_a_path_that_leaves_the_folder_is_refused(self):
        with self.assertRaises(packages.PackageError) as caught:
            self.package({"../outside.hda": "x", "otls/example_one.hda": "1", "icons/one.svg": "s"})
        self.assertIn("'../outside.hda' is not a plain relative path", str(caught.exception))

    def test_a_need_outside_the_package_is_refused(self):
        with self.assertRaises(packages.PackageError) as caught:
            self.package(nodes=[_node("One", "one", needs=["Cop/elsewhere::x::0.1"])])
        self.assertIn("One needs Cop/elsewhere::x::0.1", str(caught.exception))

    def test_a_listed_file_missing_from_root_is_refused(self):
        _write(os.path.join(self.root, "icons", "one.svg"), "s")
        with self.assertRaises(packages.PackageError) as caught:
            addons.write(self.out, self.fields(), self.root,
                         ["otls/example_one.hda", "icons/one.svg"])
        self.assertIn("no file otls/example_one.hda", str(caught.exception))


class TheReaderTest(_Workspace):

    def _rewritten(self, path, manifest=None, extra=None):
        """A copy of `path` with its manifest replaced and members added, as a damaged store copy."""
        copy = path + ".edited"
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(copy, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if name == packages.MANIFEST and manifest is not None:
                    data = json.dumps(manifest).encode("utf-8")
                target.writestr(name, data)
            for name, data in (extra or {}).items():
                target.writestr(name, data)
        return copy

    def test_an_unlisted_member_is_refused(self):
        copy = self._rewritten(self.package(), extra={"otls/stowaway.hda": "x"})
        with self.assertRaises(packages.PackageError) as caught:
            addons.read(copy)
        self.assertIn("member otls/stowaway.hda is not listed", str(caught.exception))

    def test_a_newer_format_is_refused(self):
        path = self.package()
        manifest = dict(addons.read(path), format=packages.FORMAT + 1)
        with self.assertRaises(packages.PackageError) as caught:
            addons.read(self._rewritten(path, manifest))
        self.assertIn("newer than", str(caught.exception))

    def test_the_library_import_refuses_an_add_on(self):
        library = types.SimpleNamespace(dir=os.path.join(self.dir, "library") + os.sep)
        with self.assertRaises(packages.PackageError) as caught:
            packages.import_package({}, library, self.package())
        self.assertIn("is an add-on, not library assets", str(caught.exception))


class TheInstallerTest(_Workspace):

    def _folder(self):
        return os.path.join(self.amaze, addons.ROOT, "shapes")

    def test_an_install_lands_as_its_folder_with_its_manifest(self):
        addons.install(self.package(), self.amaze, running=(22, 0, 466))
        self.assertTrue(os.path.isfile(os.path.join(self._folder(), "otls", "example_one.hda")))
        self.assertEqual("1.2.3", addons.installed(self.amaze, "shapes")["version"])

    def test_an_update_replaces_the_folder_whole(self):
        old = {"otls/example_one.hda": "1", "icons/one.svg": "s", "scripts/python/old.py": "x"}
        addons.install(self.package(old), self.amaze, running=(22, 0, 466))
        shutil.rmtree(self.root)
        addons.install(self.package(version="1.3.0"), self.amaze, running=(22, 0, 466))
        self.assertFalse(os.path.exists(os.path.join(self._folder(), "scripts", "python", "old.py")),
                         "a file the new version dropped stayed behind")
        self.assertEqual("1.3.0", addons.installed(self.amaze, "shapes")["version"])

    def test_an_older_houdini_is_refused_and_nothing_changes(self):
        addons.install(self.package(), self.amaze, running=(22, 0, 466))
        with self.assertRaises(packages.PackageError) as caught:
            addons.install(self.package(version="2.0.0"), self.amaze, running=(21, 0, 729))
        self.assertIn("needs Houdini 22.0 or newer", str(caught.exception))
        self.assertEqual("1.2.3", addons.installed(self.amaze, "shapes")["version"])

    def test_a_damaged_member_leaves_the_old_version_in_place(self):
        addons.install(self.package(), self.amaze, running=(22, 0, 466))
        path = self.package({"otls/example_one.hda": "PAYLOAD-TO-DAMAGE", "icons/one.svg": "s"},
                            version="1.3.0")
        stored = path + ".stored"
        with zipfile.ZipFile(path) as source, \
                zipfile.ZipFile(stored, "w", zipfile.ZIP_STORED) as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
        with open(stored, "r+b") as handle:
            handle.seek(handle.read().index(b"PAYLOAD-TO-DAMAGE"))
            handle.write(b"X")
        with self.assertRaises(packages.PackageError):
            addons.install(stored, self.amaze, running=(22, 0, 466))
        self.assertEqual("1.2.3", addons.installed(self.amaze, "shapes")["version"])
        self.assertFalse(os.path.exists(self._folder() + ".installing"))


class AnAmazeUpdateKeepsItsAddOnsTest(_Workspace):

    def test_the_updater_carries_the_add_ons_into_the_new_install(self):
        _write(os.path.join(self.amaze, "scripts", "old.txt"), "the version being replaced")
        _write(os.path.join(self.amaze, addons.ROOT, "shapes", packages.MANIFEST), "{}")
        staged = os.path.join(self.dir, "staged")
        _write(os.path.join(staged, "scripts", "new.txt"), "the release")
        updater.apply_update(staged, self.amaze)
        self.assertTrue(os.path.isfile(os.path.join(self.amaze, "scripts", "new.txt")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.amaze, addons.ROOT, "shapes", packages.MANIFEST)),
            "the update deleted the installed add-ons with the old install")


class ThePackageTemplateTest(unittest.TestCase):

    def test_the_template_puts_every_add_on_folder_on_the_path(self):
        with open(os.path.join(REPO, "Amaze.json"), encoding="utf-8") as handle:
            template = json.load(handle)
        self.assertNotIn("path", template, "`path` is deprecated for `hpath`")
        wanted = ["$AMAZE"] + ["$AMAZE/%s/%s" % (addons.ROOT, f) for f in addons.FOLDERS]
        self.assertEqual(wanted, template["hpath"])

    def test_the_readme_shows_the_template_as_it_is(self):
        with open(os.path.join(REPO, "Amaze.json"), encoding="utf-8") as handle:
            template = json.load(handle)
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        shown = readme.split("```json", 1)[1].split("```", 1)[0]
        self.assertEqual(template, json.loads(shown))


if __name__ == "__main__":
    unittest.main()
