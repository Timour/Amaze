"""Add-on packages: the one writer, the refusing reader, the whole-folder installer, the carry."""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import addons, matx_sources, packages, updater
from amaze.tests import test_support

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))


def _node(label, kind, icon="icons/one.svg", group=None, short="Does one thing."):
    node = {"label": label, "type": "Sop/example::%s::0.1" % kind,
            "file": "otls/example_%s.hda" % kind, "addon_icon": icon,
            "short_description": short, "description": ""}
    if group is not None:
        node["group"] = group
    return node


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
        made = {"name": "Example", "folder": "example", "version": version,
                "author": "Test Author", "houdini": "22.0.466", "houdini_min": "22.0",
                "changelog": "- A change.", "nodes": nodes or [_node("One", "one")]}
        made.update(extra)
        return made

    def package(self, files=None, version="1.2.3", **extra):
        files = files or {"otls/example_one.hda": "hda one", "icons/one.svg": "<svg/>"}
        for member, text in files.items():
            test_support.write_text(os.path.join(self.root, *member.split("/")), text)
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
        nodes = [_node("One", "one", group="Pair"), _node("Two", "two", group="Pair")]
        self.assertEqual(2, len(addons.read(self.package(files, nodes=nodes))["nodes"]))

    def test_nodes_sharing_a_group_are_one_row_in_package_order(self):
        files = {"otls/example_%s.hda" % k: k for k in ("one", "two", "three")}
        files["icons/one.svg"] = "s"
        nodes = [_node("Three", "three"), _node("One", "one", group="Pair"),
                 _node("Two", "two", group="Pair")]
        rows = addons.rows(addons.read(self.package(files, nodes=nodes)))
        self.assertEqual([("Three", ["Three"]), ("Pair", ["One", "Two"])],
                         [(row["name"], [n["label"] for n in row["nodes"]]) for row in rows])
        self.assertEqual(("icons/one.svg", "Does one thing."),
                         (rows[1]["addon_icon"], rows[1]["short_description"]))

    def test_an_add_on_icon_must_be_a_picture_the_tab_draws(self):
        files = {"otls/example_one.hda": "1", "icons/one.svg": "s", "icons/one.tif": "t"}
        with self.assertRaises(packages.PackageError) as caught:
            self.package(files, nodes=[_node("One", "one", icon="icons/one.tif")])
        self.assertIn("One: addon_icon 'icons/one.tif' is not an .svg or .png",
                      str(caught.exception))

    def test_a_group_whose_nodes_disagree_is_refused(self):
        files = {"otls/example_one.hda": "1", "otls/example_two.hda": "2", "icons/one.svg": "s"}
        nodes = [_node("One", "one", group="Pair"),
                 _node("Two", "two", group="Pair", short="Does another.")]
        with self.assertRaises(packages.PackageError) as caught:
            self.package(files, nodes=nodes)
        self.assertIn("One and Two share group 'Pair' but differ in short_description",
                      str(caught.exception))

    def test_a_node_in_no_group_is_its_own_row_even_under_a_groups_name(self):
        files = {"otls/example_%s.hda" % k: k for k in ("one", "two", "three")}
        files["icons/one.svg"] = "s"
        nodes = [_node("Pair", "one", group=""), _node("Two", "two", group="Pair"),
                 _node("Three", "three")]
        rows = addons.rows(addons.read(self.package(files, nodes=nodes)))
        self.assertEqual([("Pair", ["Pair"]), ("Pair", ["Two"]), ("Three", ["Three"])],
                         [(row["name"], [n["label"] for n in row["nodes"]]) for row in rows])

    def test_a_group_that_is_not_text_is_refused(self):
        with self.assertRaises(packages.PackageError) as caught:
            self.package(nodes=[_node("One", "one", group=5)])
        self.assertIn("One: group is not text", str(caught.exception))

    def test_a_member_passed_twice_is_written_once(self):
        test_support.write_text(os.path.join(self.root, "otls", "example_one.hda"), "1")
        test_support.write_text(os.path.join(self.root, "icons", "one.svg"), "s")
        path = addons.write(self.out, self.fields(), self.root,
                            ["otls/example_one.hda", "icons/one.svg", "icons/one.svg"])
        with zipfile.ZipFile(path) as bundle:
            self.assertEqual(1, bundle.namelist().count("icons/one.svg"))

    def test_a_beta_is_its_version_marked_and_no_other_mark_is_taken(self):
        path = self.package(version="1.2.4-beta")
        self.assertEqual("Example-1.2.4-beta.amazepkg", os.path.basename(path))
        self.assertEqual("1.2.4-beta", addons.read(path)["version"])
        for version in ("1.2.4-beta2", "1.2.4-alpha", "1.2.4beta", "1.2.4-BETA"):
            with self.subTest(version=version), self.assertRaises(packages.PackageError):
                self.package(version=version)

    def test_every_problem_is_named_at_once(self):
        node = _node("One", "one")
        del node["description"]
        with self.assertRaises(packages.PackageError) as caught:
            self.package(version="1.2", nodes=[node], folder="../elsewhere")
        for named in ("version '1.2' is not X.Y.Z",
                      "folder '../elsewhere' is not a plain lowercase name",
                      "lacks description"):
            self.assertIn(named, str(caught.exception))

    def test_a_path_that_leaves_the_folder_is_refused(self):
        with self.assertRaises(packages.PackageError) as caught:
            self.package({"../outside.hda": "x", "otls/example_one.hda": "1", "icons/one.svg": "s"})
        self.assertIn("'../outside.hda' is not a plain relative path", str(caught.exception))

    def test_a_listed_file_missing_from_root_is_refused(self):
        test_support.write_text(os.path.join(self.root, "icons", "one.svg"), "s")
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

    def test_a_package_in_the_old_shape_is_refused(self):
        path = self.package()
        manifest = addons.read(path)
        for node in manifest["nodes"]:
            node["icon"] = node.pop("addon_icon")
            del node["short_description"]
        with self.assertRaises(packages.PackageError) as caught:
            addons.read(self._rewritten(path, manifest))
        self.assertIn("a node lacks addon_icon, short_description", str(caught.exception))

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
        return os.path.join(self.amaze, addons.ROOT, "example")

    def test_an_install_lands_as_its_folder_with_its_manifest(self):
        addons.install(self.package(), self.amaze, running=(22, 0, 466))
        self.assertTrue(os.path.isfile(os.path.join(self._folder(), "otls", "example_one.hda")))
        self.assertEqual("1.2.3", addons.installed(self.amaze, "example")["version"])

    def test_an_install_writes_the_package_file_houdini_loads_it_by(self):
        addons.install(self.package(folder="any_tool"), self.amaze, running=(22, 0, 466))
        with open(addons.package_file(self.amaze, "any_tool"), encoding="utf-8") as handle:
            self.assertEqual({"hpath": ["$HOUDINI_PACKAGE_PATH/any_tool"]}, json.load(handle))

    def test_an_update_replaces_the_folder_whole(self):
        old = {"otls/example_one.hda": "1", "icons/one.svg": "s", "scripts/python/old.py": "x"}
        addons.install(self.package(old), self.amaze, running=(22, 0, 466))
        shutil.rmtree(self.root)
        addons.install(self.package(version="1.3.0"), self.amaze, running=(22, 0, 466))
        self.assertFalse(os.path.exists(os.path.join(self._folder(), "scripts", "python", "old.py")),
                         "a file the new version dropped stayed behind")
        self.assertEqual("1.3.0", addons.installed(self.amaze, "example")["version"])

    def test_an_older_houdini_is_refused_and_nothing_changes(self):
        addons.install(self.package(), self.amaze, running=(22, 0, 466))
        with self.assertRaises(packages.PackageError) as caught:
            addons.install(self.package(version="2.0.0"), self.amaze, running=(21, 0, 729))
        self.assertIn("needs Houdini 22.0 or newer", str(caught.exception))
        self.assertEqual("1.2.3", addons.installed(self.amaze, "example")["version"])

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
        self.assertEqual("1.2.3", addons.installed(self.amaze, "example")["version"])
        self.assertFalse(os.path.exists(self._folder() + ".installing"))


class _ThreeRows(_Workspace):
    """An add-on of three nodes, two of them one group: rows Pair (One, Two) and Three."""

    FILES = {"otls/example_one.hda": "1", "otls/example_two.hda": "2",
             "otls/example_three.hda": "3", "icons/one.svg": "s"}

    def three_rows(self, version="1.2.3"):
        nodes = [_node("One", "one", group="Pair"), _node("Two", "two", group="Pair"),
                 _node("Three", "three")]
        return self.package(dict(self.FILES), version=version, nodes=nodes)

    def hda(self, kind, off=False):
        return os.path.join(self.amaze, addons.ROOT, "example", *(["off"] if off else []),
                            "otls", "example_%s.hda" % kind)


class TheSwitchTest(_ThreeRows):

    def test_off_moves_a_groups_files_out_of_houdinis_reach_and_on_brings_them_back(self):
        pair, three = addons.rows(addons.install(self.three_rows(), self.amaze, running=(22, 0, 466)))
        addons.set_on(self.amaze, "example", pair, False)
        self.assertEqual((False, True), (addons.is_on(self.amaze, "example", pair),
                                         addons.is_on(self.amaze, "example", three)))
        self.assertEqual([True, True, False, False],
                         [os.path.isfile(self.hda("one", off=True)),
                          os.path.isfile(self.hda("two", off=True)),
                          os.path.isfile(self.hda("one")), os.path.isfile(self.hda("two"))])
        addons.set_on(self.amaze, "example", pair, True)
        self.assertTrue(addons.is_on(self.amaze, "example", pair))
        self.assertTrue(os.path.isfile(self.hda("one")) and os.path.isfile(self.hda("two")))


class TheStoreTest(_ThreeRows):

    def test_the_newest_version_of_each_add_on_is_found(self):
        tree = [{"type": "blob", "path": "addons/Example-1.2.3.amazepkg"},
                {"type": "blob", "path": "addons/Example-1.10.0.amazepkg"},
                {"type": "blob", "path": "addons/Other-Tool-0.1.0.amazepkg"},
                {"type": "blob", "path": "packages/materials/Example-9.0.0.amazepkg"},
                {"type": "blob", "path": "addons/deeper/Example-9.0.0.amazepkg"},
                {"type": "blob", "path": "addons/Example.amazepkg"},
                {"type": "tree", "path": "addons/Example-9.0.0.amazepkg"}]
        with mock.patch.object(matx_sources, "get_json", lambda url: {"tree": tree}):
            found = addons.store_versions()
        raw = matx_sources.AmazeSource.RAW_BASE
        self.assertEqual({"Example": ("1.10.0", raw + "addons/Example-1.10.0.amazepkg"),
                          "Other-Tool": ("0.1.0", raw + "addons/Other-Tool-0.1.0.amazepkg")}, found)

    def test_releases_and_betas_are_listed_apart_never_both(self):
        tree = [{"type": "blob", "path": "addons/Example-1.2.4.amazepkg"},
                {"type": "blob", "path": "addons/Example-1.2.4-beta.amazepkg"},
                {"type": "blob", "path": "addons/Example-1.2.7-beta.amazepkg"},
                {"type": "blob", "path": "addons/Example-1.10.0-beta.amazepkg"},
                {"type": "blob", "path": "addons/Other-0.1.0.amazepkg"}]
        with mock.patch.object(matx_sources, "get_json", lambda url: {"tree": tree}):
            releases, betas = addons.store_versions(), addons.store_versions(betas=True)
        raw = matx_sources.AmazeSource.RAW_BASE
        self.assertEqual({"Example": ("1.2.4", raw + "addons/Example-1.2.4.amazepkg"),
                          "Other": ("0.1.0", raw + "addons/Other-0.1.0.amazepkg")}, releases)
        self.assertEqual({"Example": ("1.10.0-beta",
                                      raw + "addons/Example-1.10.0-beta.amazepkg")}, betas)

    def test_update_crosses_kinds_whatever_the_number_and_within_one_only_goes_up(self):
        for installed, offer, expected in ((None, "1.0.0", True),
                                           ("1.2.5-beta", "1.2.4", True),
                                           ("1.2.7", "1.2.5-beta", True),
                                           ("1.2.4", "1.2.4", False),
                                           ("1.2.4", "1.10.0", True),
                                           ("1.10.0", "1.2.4", False),
                                           ("1.2.4-beta", "1.2.7-beta", True),
                                           ("1.2.7-beta", "1.2.7-beta", False)):
            with self.subTest(installed=installed, offer=offer):
                self.assertEqual(expected, addons.wanted(installed, offer))

    def test_an_update_from_the_store_keeps_an_off_row_off(self):
        pair, _three = addons.rows(addons.install(self.three_rows(), self.amaze,
                                                  running=(22, 0, 466)))
        addons.set_on(self.amaze, "example", pair, False)
        newer = self.three_rows(version="1.3.0")

        def download(url, dest, on_bytes=None):
            shutil.copy(newer, dest)
            return dest

        with mock.patch.object(matx_sources, "download", download):
            addons.fetch_and_install("https://example.invalid/addons/Example-1.3.0.amazepkg",
                                     self.amaze, running=(22, 0, 466))
        self.assertEqual("1.3.0", addons.installed(self.amaze, "example")["version"])
        self.assertTrue(os.path.isfile(self.hda("one", off=True)), "the update turned Pair back on")
        self.assertTrue(os.path.isfile(self.hda("three")), "the update turned Three off")


class AnAmazeUpdateKeepsItsAddOnsTest(_Workspace):

    def test_the_updater_carries_the_add_ons_into_the_new_install(self):
        test_support.write_text(os.path.join(self.amaze, "scripts", "old.txt"), "the version being replaced")
        test_support.write_text(os.path.join(self.amaze, addons.ROOT, "example", packages.MANIFEST), "{}")
        staged = os.path.join(self.dir, "staged")
        test_support.write_text(os.path.join(staged, "scripts", "new.txt"), "the release")
        updater.apply_update(staged, self.amaze)
        self.assertTrue(os.path.isfile(os.path.join(self.amaze, "scripts", "new.txt")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.amaze, addons.ROOT, "example", packages.MANIFEST)),
            "the update deleted the installed add-ons with the old install")

    HOME_MADE = os.path.join(addons.ROOT, "mytool", "otls", "mytool.hda")    # never in the store

    def _release(self, name, which):
        test_support.write_text(os.path.join(self.dir, name, "scripts", "which.txt"), which)
        return os.path.join(self.dir, name)

    def _which(self):
        with open(os.path.join(self.amaze, "scripts", "which.txt"), encoding="utf-8") as handle:
            return handle.read()

    def _add_on_files(self):
        """Every add-on file anywhere in the workspace, relative to it."""
        return sorted(os.path.relpath(os.path.join(folder, name), self.dir)
                      for folder, _dirs, names in os.walk(self.dir)
                      for name in names if addons.ROOT in folder.split(os.sep))

    def test_a_carry_that_fails_refuses_the_update_and_keeps_the_old_install(self):
        """The refusal names its reason, the old install stays whole, the next update carries."""
        test_support.write_text(os.path.join(self.amaze, "scripts", "which.txt"), "1.0")
        test_support.write_text(os.path.join(self.amaze, self.HOME_MADE), "a home-made add-on")
        real, calls = addons.carry, []

        def held_once(old, new):
            calls.append(new)
            if len(calls) == 1:
                raise OSError(13, "Permission denied", os.path.join(old, self.HOME_MADE))
            return real(old, new)

        with mock.patch.object(addons, "carry", held_once):
            with self.assertRaises(OSError) as refused:
                updater.apply_update(self._release("staged1", "1.1"), self.amaze)
            self.assertIn("add-ons", str(refused.exception))
            self.assertIn("Permission denied", str(refused.exception), "the refusal lost its reason")
            self.assertEqual("1.0", self._which(), "a refused update still replaced the install")
            self.assertEqual([os.path.join("Amaze", self.HOME_MADE)], self._add_on_files(),
                             "a refused update moved the add-ons out of the install")
            updater.apply_update(self._release("staged2", "1.2"), self.amaze)
        self.assertEqual("1.2", self._which())
        self.assertEqual([os.path.join("Amaze", self.HOME_MADE)], self._add_on_files(),
                         "after the next update the add-ons are not in the install alone")

    def test_a_leftover_beside_the_install_gives_its_add_ons_back_before_it_goes(self):
        """`<install>.replacing` from an older build can hold the only copy of the add-ons."""
        test_support.write_text(os.path.join(self.amaze, "scripts", "which.txt"), "1.1")
        leftover = self.amaze + ".replacing"
        test_support.write_text(os.path.join(leftover, "scripts", "which.txt"), "1.0")
        test_support.write_text(os.path.join(leftover, self.HOME_MADE), "a home-made add-on")
        updater.apply_update(self._release("staged", "1.2"), self.amaze)
        self.assertEqual("1.2", self._which())
        self.assertEqual([os.path.join("Amaze", self.HOME_MADE)], self._add_on_files(),
                         "the leftover was deleted with the only copy of the add-ons in it")
        self.assertFalse(os.path.exists(leftover))

    def test_a_leftover_whose_add_ons_cannot_be_carried_is_kept(self):
        test_support.write_text(os.path.join(self.amaze, "scripts", "which.txt"), "1.1")
        leftover = self.amaze + ".replacing"
        test_support.write_text(os.path.join(leftover, self.HOME_MADE), "a home-made add-on")
        with mock.patch.object(addons, "carry", side_effect=OSError(28, "No space left")):
            with self.assertRaises(OSError):
                updater.apply_update(self._release("staged", "1.2"), self.amaze)
        self.assertEqual([os.path.join("Amaze.replacing", self.HOME_MADE)], self._add_on_files(),
                         "a leftover holding add-ons was deleted without carrying them")
        self.assertEqual("1.1", self._which())


class TheCarryTest(_Workspace):
    """`carry` copies what a new tree lacks; the old install keeps its add-ons until it goes."""

    def setUp(self):
        super().setUp()
        self.new = os.path.join(self.dir, "staged")
        for member in ("a/otls/a.hda", "a.json", "b/otls/b.hda", "b.json"):
            test_support.write_text(os.path.join(self.amaze, addons.ROOT, *member.split("/")), "old " + member)

    def _tree(self, root):
        found = []
        for folder, _dirs, names in os.walk(os.path.join(root, addons.ROOT)):
            found += [os.path.relpath(os.path.join(folder, name), root) for name in names]
        return sorted(found)

    def test_the_carry_copies_only_what_the_new_tree_lacks(self):
        test_support.write_text(os.path.join(self.new, addons.ROOT, "a", "otls", "a.hda"), "installed since")
        addons.carry(self.amaze, self.new)
        with open(os.path.join(self.new, addons.ROOT, "a", "otls", "a.hda"), encoding="utf-8") as fh:
            self.assertEqual("installed since", fh.read(), "the carry wrote over an add-on there")
        self.assertEqual(self._tree(self.amaze), self._tree(self.new))
        self.assertEqual(4, len(self._tree(self.amaze)), "the carry emptied the old tree")

    def test_a_carry_that_dies_part_way_takes_back_what_it_copied(self):
        real = shutil.copytree

        def dies_in_b(src, dst, *args, **kwargs):
            if os.path.basename(src) == "b":
                test_support.write_text(os.path.join(dst, "otls", "fragment"), "half")
                why = "[Errno 28] No space left on device"
                raise shutil.Error([(os.path.join(src, "otls", "b.hda"), dst, why)])
            return real(src, dst, *args, **kwargs)

        os.makedirs(self.new)
        with mock.patch.object(shutil, "copytree", dies_in_b):
            with self.assertRaises(OSError) as failed:
                addons.carry(self.amaze, self.new)
        self.assertEqual("[Errno 28] No space left on device", str(failed.exception),
                         "the reason reads as copytree's list rather than its first cause")
        self.assertEqual([], self._tree(self.new), "a failed carry left part of the add-ons behind")
        self.assertFalse(os.path.exists(os.path.join(self.new, addons.ROOT)))
        self.assertEqual(4, len(self._tree(self.amaze)), "a failed carry lost add-on files")


class ThePackageTemplateTest(unittest.TestCase):

    def test_the_template_reads_every_add_on_from_amazes_add_on_folder(self):
        with open(os.path.join(REPO, "Amaze.json"), encoding="utf-8") as handle:
            template = json.load(handle)
        self.assertNotIn("path", template, "`path` is deprecated for `hpath`")
        self.assertEqual(["$AMAZE"], template["hpath"])
        amaze = template["env"][0]["AMAZE"]
        self.assertEqual(amaze + "/" + addons.ROOT, template["package_path"],
                         "package_path cannot use $AMAZE, so it repeats the folder in full")

    def test_the_readme_shows_the_template_as_it_is(self):
        with open(os.path.join(REPO, "Amaze.json"), encoding="utf-8") as handle:
            template = json.load(handle)
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        shown = readme.split("```json", 1)[1].split("```", 1)[0]
        self.assertEqual(template, json.loads(shown))


if __name__ == "__main__":
    unittest.main()
