"""Add-ons: one test per requirement in docs/requirements/add-ons.md."""

import contextlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from amaze import messages
from amaze.core import addons, matx_sources, packages
from amaze.tests import faults, test_support

HOUDINI = (22, 0, 466)
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 4))


def _node(label, kind, group=None):
    node = {"label": label, "type": "Sop/example::%s" % kind, "file": "otls/%s.hda" % kind,
            "addon_icon": "icons/one.svg", "short_description": "Does one thing.",
            "description": ""}
    return dict(node, group=group) if group else node


class _AddOns(unittest.TestCase):
    """An Amaze install holding one other add-on and its own files."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_addons_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.amaze = os.path.join(self.dir, "Amaze")
        test_support.put(self.amaze, "scripts/python/amaze/__init__.py", "# Amaze itself")
        test_support.put(self.amaze, "addons/other/otls/other.hda", "another add-on")
        test_support.put(self.amaze, "addons/other.json", "{}")

    def package(self, version="1.2.3", name="Example") -> str:
        """An add-on package of three nodes, One and Two grouped as Pair; its file's path."""
        nodes = [_node("One", "one", "Pair"), _node("Two", "two", "Pair"), _node("Three", "three")]
        root = os.path.join(self.dir, "source", version)
        files = ["icons/one.svg"] + [node["file"] for node in nodes]
        for member in files:
            test_support.put(root, member, "%s of %s" % (member, version))
        made = {"name": name, "folder": "example", "version": version, "author": "A",
                "houdini": "22.0.466", "houdini_min": "22.0", "changelog": "-", "nodes": nodes}
        store = os.path.join(self.dir, "store", version)
        os.makedirs(store, exist_ok=True)
        return addons.write(store, made, root, files)

    def rewritten(self, path, change=None, extra=None) -> str:
        """A copy of a package whose manifest `change` alters, with `extra` members added."""
        copy = tempfile.mkstemp(".amazepkg", dir=os.path.dirname(path))[1]
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(copy, "w") as target:
            manifest = json.loads(source.read(packages.MANIFEST))
            (change or (lambda m: None))(manifest)
            target.writestr(packages.MANIFEST, json.dumps(manifest))
            for name in source.namelist():
                if name != packages.MANIFEST:
                    target.writestr(name, source.read(name))
            for name, data in (extra or {}).items():
                target.writestr(name, data)
        return copy

    def install(self, path, running=HOUDINI, disk=None) -> dict:
        return addons.install(path, self.amaze, running, disk=disk)

    def state(self) -> dict:
        return test_support.library_state(self.dir)

    def hda(self, kind, off=False) -> str:
        return os.path.join(self.amaze, addons.ROOT, "example", *(["off"] if off else []),
                            "otls", "%s.hda" % kind)


class AddOnTest(_AddOns):

    def test_ao01_an_install_update_or_switch_writes_only_its_own_add_on(self):
        def outside():
            return {name: data for name, data in self.state().items()
                    if not name.startswith(("Amaze/addons/example", "source/", "store/"))}

        before = outside()
        pair = addons.rows(self.install(self.package()))[0]
        self.install(self.package("1.3.0"))
        addons.set_on(self.amaze, "example", pair, False)
        addons.set_on(self.amaze, "example", pair, True)
        self.assertEqual(before, outside(), "an add-on wrote or removed a file outside its own")
        escaping = self.rewritten(self.package("1.4.0"), lambda m: m["files"].append("../x.hda"),
                                  {"../x.hda": "escaped"})
        with self.assertRaises(packages.PackageError):
            self.install(escaping)
        self.assertEqual(before, outside(), "a member path left the add-on's folder")
        self.assertEqual("1.3.0", addons.installed(self.amaze, "example")["version"])

    def test_ao10_an_update_cut_off_anywhere_leaves_one_whole_version(self):
        old, new = self.package("1.0.0"), self.package("2.0.0")
        counting = faults.FaultDisk()
        self.install(old)
        self.install(new, disk=counting)
        cuts = [("swap step %d" % step, faults.FaultDisk(cut_at=step), contextlib.nullcontext())
                for step in range(1, counting.steps + 1)]
        cuts.append(("unpacking", None,
                     mock.patch.object(packages, "copy_member", side_effect=faults.Cut)))
        for where, disk, during in cuts:
            with self.subTest(cut=where):
                shutil.rmtree(os.path.join(self.amaze, addons.ROOT, "example"), True)
                self.install(old)
                with during, self.assertRaises(faults.Cut):
                    self.install(new, disk=disk)
                listed = [m for folder, m in addons.installed_all(self.amaze)
                          if folder == "example"]
                self.assertEqual(1, len(listed), "no version, or two, after the next read")
                version = listed[0]["version"]
                with open(self.hda("three"), encoding="utf-8") as handle:
                    self.assertEqual("otls/three.hda of %s" % version, handle.read())

    def test_ao11_a_package_that_cannot_install_whole_changes_nothing(self):
        self.install(self.package())
        newer = self.package("1.3.0")
        damaged = test_support.put(self.dir, "damaged.amazepkg", b"PK\x03\x04 not a zip")
        stored = self.rewritten(newer)
        with open(stored, "r+b") as handle:    # a member that does not read back whole
            handle.seek(handle.read().index(b"otls/three.hda of 1.3.0"))
            handle.write(b"X")
        cases = {
            "damaged zip": (damaged, HOUDINI),
            "damaged member": (stored, HOUDINI),
            "missing member": (self.rewritten(newer, lambda m: m["files"].append("otls/no.hda")),
                               HOUDINI),
            "unlisted member": (self.rewritten(newer, extra={"otls/extra.hda": "x"}), HOUDINI),
            "newer format": (self.rewritten(newer, lambda m: m.update(format=99)), HOUDINI),
            "wrong field": (self.rewritten(newer, lambda m: m.update(version=5)), HOUDINI),
            "older Houdini": (newer, (21, 0, 0)),
        }
        for name, (path, running) in cases.items():
            with self.subTest(name):
                before = self.state()
                with self.assertRaises(packages.PackageError) as caught:
                    self.install(path, running)
                self.assertTrue(str(caught.exception))
                self.assertEqual(before, self.state(), "a refused package changed a file")
        with self.subTest("over the size cap"), \
                mock.patch.object(addons, "MAX_UNPACKED_BYTES", 10), \
                self.assertRaises(packages.PackageError):
            self.install(newer)
        self.assertEqual("1.2.3", addons.installed(self.amaze, "example")["version"])

    def test_ao12_a_package_never_replaces_an_add_on_of_another_name(self):
        self.install(self.package())
        intruder = self.package("9.0.0", name="Intruder")
        before = self.state()
        with self.assertRaises(packages.PackageError) as caught:
            self.install(intruder)
        self.assertEqual(messages.ADDON_FOLDER_TAKEN % ("Intruder", "example", "Example"),
                         str(caught.exception))
        self.assertEqual(before, self.state())

    def test_ao20_check_offers_the_newer_ones_of_one_kind(self):
        tree = [{"type": "blob", "path": "addons/Example-%s.amazepkg" % version}
                for version in ("1.2.4", "1.10.0", "1.11.0-beta", "1.2.9-beta")]
        with mock.patch.object(matx_sources, "get_json", lambda url: {"tree": tree}):
            releases, betas = addons.store_versions(), addons.store_versions(betas=True)
        self.assertEqual("1.10.0", releases["Example"][0])
        self.assertEqual("1.11.0-beta", betas["Example"][0])
        self.assertTrue(addons.wanted("1.9.0", "1.10.0"))
        self.assertFalse(addons.wanted("1.10.0", "1.10.0"))
        self.assertTrue(addons.wanted("1.12.0", "1.11.0-beta"), "the other kind is offered")

    def test_ao21_update_names_each_one_installed_when_esc_stops_the_rest(self):
        from amaze.actions import addons as addon_actions
        installed = []

        def fetch(url, root, running, **how):
            if installed:
                raise OSError(messages.DOWNLOAD_STOPPED)
            installed.append(url)

        found = [("Example", "1.3.0", "first"), ("Other", "2.0.0", "second")]
        with mock.patch.object(addons, "fetch_and_install", fetch):
            said = addon_actions.install(found, self.amaze)
        self.assertEqual(["first"], installed)
        self.assertEqual("%s %s" % (messages.ADDONS_INSTALLED % "Example 1.3.0",
                                    messages.ADDONS_REST_STOPPED), said)

    def test_ao22_off_moves_a_rows_files_and_an_update_keeps_it_off(self):
        pair = addons.rows(self.install(self.package()))[0]
        addons.set_on(self.amaze, "example", pair, False)
        self.assertTrue(all(os.path.isfile(self.hda(kind, off=True)) for kind in ("one", "two")))
        self.assertFalse(addons.is_on(self.amaze, "example", pair))
        self.install(self.package("1.3.0"))
        self.assertTrue(os.path.isfile(self.hda("one", off=True)), "the update turned Pair on")
        self.assertTrue(os.path.isfile(self.hda("three")), "the update turned Three off")
        addons.set_on(self.amaze, "example", pair, True)
        self.assertTrue(all(os.path.isfile(self.hda(kind)) for kind in ("one", "two")))

    def test_ao23_houdini_loads_each_add_on_once_through_its_package_file(self):
        self.install(self.package())
        with open(addons.package_file(self.amaze, "example"), encoding="utf-8") as handle:
            self.assertEqual({"hpath": ["$HOUDINI_PACKAGE_PATH/example"]}, json.load(handle))
        with open(os.path.join(REPO, "Amaze.json"), encoding="utf-8") as handle:
            template = json.load(handle)
        self.assertEqual(template["env"][0]["AMAZE"] + "/" + addons.ROOT,
                         template["package_path"])
        self.assertIs(True, template.get("load_package_once"))

    def test_ao24_one_row_per_group_and_an_unreadable_add_on_is_not_listed(self):
        manifest = self.install(self.package())
        self.assertEqual(["Pair", "Three"], [row["name"] for row in addons.rows(manifest)])
        test_support.put(self.amaze, "addons/other/package.json", "{not json")
        self.assertEqual(["example"], [folder for folder, _m in addons.installed_all(self.amaze)])


if __name__ == "__main__":
    unittest.main()
