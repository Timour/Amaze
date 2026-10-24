"""Tile icons: a chosen symbol on a chosen colour, instead of a tile with nothing to show. - The geometry is the part worth pinning. It was read off the design template by measuring its clipboard against Feather's own clipboard.svg - 250px of ink, a 10px stroke, centred on 512 - and none of that is recoverable from the code if it drifts. So these tests measure rendered pixels rather than trusting the constants: the template's own icon must land where the template put it, and no icon may exceed the 250px rule whatever its shape or the chosen line weight. - The rest is about not losing anything: the render underneath is never overwritten, a nonsense choice degrades to "no icon" instead of a broken grid, and the cache key changes with the icon so a tile cannot be served yesterday's picture."""

import ast
import contextlib
import inspect
import json
import os
import sys
import textwrap
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme  # noqa: E402
from amaze.actions import nodes as node_actions  # noqa: E402
from amaze.core import cop_library, tile_icons  # noqa: E402
from amaze.dialogs import icon_dialog  # noqa: E402
from amaze.helpers import theme  # noqa: E402
from amaze.panel import panel as panel_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


def ink_box(image, background="#ef8878"):
    """The rect the SYMBOL covers on a composed tile. - Measured against the background COLOUR, not the alpha channel: a composed tile is opaque edge to edge, so an alpha mask reports the whole canvas. (The composer's own internal measurement works on a bare icon over transparency, where alpha is the right question - two different measurements, both easy to get backwards. Both polarities were checked against an exhaustive pixel scan.)"""
    mask = image.createMaskFromColor(
        QtGui.QColor(background).rgb(), QtCore.Qt.MaskMode.MaskInColor
    )
    return QtGui.QRegion(QtGui.QBitmap.fromImage(mask)).boundingRect()


class GeometryTest(unittest.TestCase):
    """What the template says, measured in pixels."""

    def test_the_template_icon_lands_where_the_template_put_it(self):
        """The template draws Feather's clipboard with its path from (156,131) to (356,381). Rendered, that is those bounds grown by half the 10px stroke on each side."""
        image = tile_icons.compose("clipboard", "#ef8878", 512)
        self.assertIsNotNone(image)
        box = ink_box(image)
        self.assertEqual((151, 126, 210, 260),
                         (box.x(), box.y(), box.width(), box.height()))

    def test_no_icon_breaks_the_250px_rule(self):
        """The design rule is 250px in the widest direction on a 512x512 tile. Most Feather icons draw inside 20 of their 24 units and obey it for free; the "-off" variants slash corner to corner and have to be fitted down."""
        for weight in (tile_icons.STROKE_UNITS,
                       tile_icons.FEATHER_STROKE_UNITS):
            stroke_px = weight * tile_icons.ICON_SCALE
            limit = tile_icons.INK_SPAN + stroke_px + 2  # ink includes the stroke, half either side of the path, plus a pixel of antialiasing
            for name in tile_icons.icon_names():
                image = tile_icons.compose(name, "#ffffff", 512, weight)
                self.assertIsNotNone(image, name)
                box = ink_box(image, "#ffffff")
                self.assertLessEqual(
                    max(box.width(), box.height()), limit,
                    "%s draws %dx%d at weight %s"
                    % (name, box.width(), box.height(), weight))
        self.assertEqual(287, len(tile_icons.icon_names()),
                         "the shipped icon set changed size")

    def test_a_fitted_icon_keeps_its_stroke_weight(self):
        """The icons that shrink must not also thin out - the stroke is divided by the same factor the scale is multiplied by."""
        plain, plain_stroke = tile_icons._fit("box", 0.8)
        fitted, fitted_stroke = tile_icons._fit("cloud-off", 0.8)
        self.assertLess(fitted, plain, "cloud-off was not fitted down")
        self.assertAlmostEqual(plain * plain_stroke, fitted * fitted_stroke,
                               places=3)

    def test_the_background_fills_the_tile(self):
        image = tile_icons.compose("box", "#4af2a1", 512)
        for x, y in ((0, 0), (511, 0), (0, 511), (511, 511), (5, 256)):
            self.assertEqual("#4af2a1",
                             QtGui.QColor(image.pixel(x, y)).name())


class ChoiceTest(unittest.TestCase):
    """Storing a choice, and surviving a bad one."""

    def setUp(self):
        test_support.reset_database_singletons()
        tile_icons.forget_overrides()
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = cop_library.CopLibrary(preferences=self.prefs)
        self.addCleanup(self._clear_obj)
        self.row = self._an_asset()

    def _clear_obj(self):
        for child in hou.node("/obj").children():
            try:
                child.destroy()
            except hou.OperationFailed:
                pass

    def _an_asset(self) -> int:
        lop = hou.node("/obj").createNode("lopnet", "icon_src")
        lop.createNode("sphere")
        held = test_support.asset_ids(self.model)
        node_actions.add_asset(self.model, lop, "", "", False, name="IconMe")
        saved, = test_support.arrived(self.model, held)
        return self.model.find_asset_row_by_id(saved.mat_id)

    def test_setting_an_icon_swaps_the_tile_path(self):
        before = self.model._mat_paths[self.row]
        self.model.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        after = self.model._mat_paths[self.row]
        self.assertNotEqual(before, after)
        self.assertTrue(after.endswith("_icon.png"))
        self.assertTrue(os.path.exists(after), "the icon PNG was not written")

    def test_the_render_underneath_is_never_touched(self):
        """An icon must be reversible - so it is written BESIDE the thumbnail, and clearing brings the original path back."""
        render_path = self.model._mat_paths[self.row]
        with open(render_path, "wb") as handle:
            handle.write(b"pretend this is a rendered thumbnail")
        self.model.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        self.assertTrue(os.path.exists(render_path))
        with open(render_path, "rb") as handle:
            self.assertEqual(b"pretend this is a rendered thumbnail",
                             handle.read())
        self.model.set_tile_icon(self.row, {})
        self.assertEqual(render_path, self.model._mat_paths[self.row])

    def test_the_choice_lands_in_the_store_and_ONLY_there(self):
        """One icons.json for every section, and it is the ONE home. - The record field used to be written too, so an older build elsewhere kept reading the pick. That shim retired 2026-08-09 with the library-format bump: a build that does not know this format now latches the whole library read-only and says to update, which is the GENERAL answer to an old build meeting a new library - so a second copy of one field bought nothing and was free to drift. Schema 5 then stripped the field itself, so there is no longer a record copy to assert about."""
        self.model.set_tile_icon(self.row, {"name": "layers",
                                            "bg": "#4af2a1"})
        stored = tile_icons.override_for(
            self.prefs, self.model.tile_key(self.row))
        self.assertEqual("layers", stored.get("name"),
                         "the pick never reached the shared store")
        self.assertNotIn(
            "icon", self.model.assets[self.row].get_as_dict(),
            "the retired record field is being written again - two "
            "copies of one value, free to drift, and the schema step "
            "that strips it is undone on every save")
        self.model.set_tile_icon(self.row, {})
        self.assertEqual({}, tile_icons.override_for(
            self.prefs, self.model.tile_key(self.row)),
            "clearing the icon left the store entry behind")

    def test_the_cache_key_changes_with_the_icon(self):
        """Same asset, different picture. Without this the shared image cache serves whichever of the two was requested first."""
        plain = self.model._thumb_key(self.row)
        self.model.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        first = self.model._thumb_key(self.row)
        self.model.set_tile_icon(self.row, {"name": "layers", "bg": "#5cc9f5"})
        second = self.model._thumb_key(self.row)
        self.assertNotEqual(plain, first)
        self.assertNotEqual(first, second, "a colour change reused the key")

    def test_a_nonsense_choice_becomes_no_choice(self):
        """This reads data a user or a future version may have written - an odd value costs a fallback tile, never the grid."""
        white = {"name": "box", "bg": "#ffffff"}
        for raw, cleaned in (
                ({"name": "not-an-icon", "bg": "#4af2a1"}, {}),
                ("a string", {}),
                (None, {}),
                ({"name": "box", "bg": "???"},    # a bad COLOUR is recoverable: keep the icon, fix the bg
                 {"name": "box", "bg": tile_icons.PRESETS[0][1], "ink": "dark"}),
                ({"face": "generic"}, {"face": "generic"}),
                ({"face": "sideways"}, {}),
                (dict(white, ink="puce"), dict(white, ink="dark")),
                (white, dict(white, ink="dark")),    # saved before ink existed, so it rendered dark
                (dict(white, ink="light"), dict(white, ink="light"))):    # ink is part of the picture
            with self.subTest(raw=raw):
                self.assertEqual(cleaned, tile_icons.normalise(raw))

    def test_the_choice_survives_a_reload_from_disk(self):
        self.model.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        test_support.reset_database_singletons()
        fresh = cop_library.CopLibrary(preferences=self.prefs)
        self.assertEqual({"name": "layers", "bg": "#4af2a1",
                          "ink": "dark"},
                         fresh.tile_icon(len(fresh.assets) - 1))

    def test_a_library_without_its_png_files_still_shows_icons(self):
        """The choice lives on the asset, so a library copied without its _icon.png files composes them again rather than showing Missing Thumbnail."""
        self.model.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        os.remove(self.model._mat_paths[self.row])
        image = self.model._missing_thumb_image(self.row)
        self.assertIsNotNone(image)
        self.assertEqual("#4af2a1", QtGui.QColor(image.pixel(4, 4)).name())


class FaceRuleTest(unittest.TestCase):
    """Preview, Generic or Custom: one rule decides which face a tile shows ▸r/tile-faces."""

    def test_one_rule_picks_the_face(self):
        icon = {"name": "box", "bg": "#4af2a1"}
        for spec, default, can_preview, face in (
                (icon, "preview", True, "custom"),    # a custom icon wins over any default
                (icon, "generic", True, "custom"),
                ({}, "generic", True, "generic"),    # nothing stored shows the row's default
                ({"face": "generic"}, "preview", True, "generic"),
                ({"face": "preview"}, "preview", False, "generic")):    # a row with no picture
            with self.subTest(spec=spec, default=default, can_preview=can_preview):
                kwargs = {} if can_preview else {"can_preview": False}
                self.assertEqual(
                    face, tile_icons.face_of(spec, default, **kwargs))

    def test_every_face_is_shipped_art(self):
        from amaze.core import code_library, gradient_library, library
        for art in (library.MaterialLibrary.TILE_FACE, cop_library.CopLibrary.TILE_FACE,
                    code_library.CodeLibrary.TILE_FACE,
                    gradient_library.GradientLibrary.TILE_FACE, "icon_hip", "face_file"):
            image = tile_icons.generic_image(art)
            self.assertIsNotNone(image, "ui/%s.svg is missing or does not render" % art)
            self.assertEqual(image.width(), image.height(), art)


class FaceChoiceTest(unittest.TestCase):
    """A face choice reaches the tile through the shared model; a row's own default is not stored."""

    def setUp(self):
        test_support.reset_database_singletons()
        tile_icons.forget_overrides()
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = cop_library.CopLibrary(preferences=self.prefs)
        self.addCleanup(lambda: [child.destroy() for child in hou.node("/obj").children()])

    def _asset(self, container: str) -> int:
        network = hou.node("/obj").createNode(container, "face_src")
        network.createNode("sphere")
        held = test_support.asset_ids(self.model)
        node_actions.add_asset(self.model, network, "", "", False, name="FaceMe")
        saved, = test_support.arrived(self.model, held)
        return self.model.find_asset_row_by_id(saved.mat_id)

    def _shown(self, row):
        return self.model.data(self.model.index(row, 0),
                               QtCore.Qt.ItemDataRole.DecorationRole)

    def test_generic_reaches_the_tile_and_writes_no_picture(self):
        row = self._asset("geo")
        self.assertEqual("preview", tile_icons.face_for(self.model, row))
        self.model.set_tile_icon(row, {"face": "generic"})
        self.assertEqual({"face": "generic"}, self.model.tile_icon(row))
        self.assertEqual(tile_icons.generic_image(self.model.TILE_FACE), self._shown(row))
        self.assertFalse(os.path.exists(tile_icons.icon_image_path(
            self.prefs, self.model.assets[row].mat_id)), "Generic composed an icon file")

    def test_the_rows_own_default_is_not_stored(self):
        row = self._asset("geo")
        self.model.set_tile_icon(row, {"face": "generic"})
        self.model.set_tile_icon(row, {"face": "preview"})
        self.assertEqual({}, self.model.tile_icon(row), "choosing the default left an entry")

    def test_a_lop_setup_has_no_preview_to_choose(self):
        row = self._asset("lopnet")
        self.assertEqual("generic", tile_icons.face_for(self.model, row))
        self.model.set_tile_icon(row, {"face": "preview"})
        self.assertEqual({}, self.model.tile_icon(row), "a Preview it cannot show was stored")
        self.assertEqual(tile_icons.generic_image(self.model.TILE_FACE), self._shown(row))


class FileRowTest(unittest.TestCase):
    """The File section's rows are files with no asset record, so their choices live in the library's icons.json, keyed by path - hip rows included since the merge closed that gap."""

    def setUp(self):
        tile_icons.forget_overrides()
        self.prefs = test_support.fixture_prefs(self)

    def test_a_path_keyed_choice_round_trips(self):
        tile_icons.set_override(self.prefs, "/tmp/a.exr",
                                {"name": "image", "bg": "#5cc9f5"})
        tile_icons.forget_overrides()
        self.assertEqual({"name": "image", "bg": "#5cc9f5",
                          "ink": "dark"},
                         tile_icons.override_for(self.prefs, "/tmp/a.exr"))
        self.assertTrue(os.path.exists(
            os.path.join(self.prefs.dir, tile_icons.OVERRIDES_FILE)))
        tile_icons.set_override(self.prefs, "/tmp/a.exr", {})
        tile_icons.forget_overrides()
        self.assertEqual({}, tile_icons.override_for(self.prefs, "/tmp/a.exr"),
                         "clearing did not forget the path on disk")

    def test_an_unreadable_store_costs_icons_not_the_section(self):
        path = os.path.join(self.prefs.dir, tile_icons.OVERRIDES_FILE)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        tile_icons.forget_overrides()
        self.assertEqual({}, tile_icons.override_for(self.prefs, "/tmp/a.exr"))


class LineWeightTest(unittest.TestCase):
    """The line-weight preference in Preferences - Look."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)

    def test_the_preference_picks_the_weight(self):
        for token, units in (("template", tile_icons.STROKE_UNITS),
                             ("feather", tile_icons.FEATHER_STROKE_UNITS),
                             ("something else", tile_icons.STROKE_UNITS)):
            with self.subTest(token=token):
                self.prefs.icon_line_weight = token
                self.assertEqual(units, tile_icons.stroke_for(self.prefs))

    def test_the_weights_actually_differ_on_screen(self):
        thin = tile_icons.compose("box", "#ffffff", 512,
                                  tile_icons.STROKE_UNITS)
        bold = tile_icons.compose("box", "#ffffff", 512,
                                  tile_icons.FEATHER_STROKE_UNITS)
        self.assertGreater(ink_box(bold, "#ffffff").width(),
                           ink_box(thin, "#ffffff").width())


class InkTest(unittest.TestCase):
    """`Lines`, chosen per tile: dark ink on a light tile, light ink on a dark one. Per tile rather than global because the BACKGROUND is per tile, and dark-on-dark is an invisible icon."""

    def test_the_tokens_map_to_the_design_colours(self):
        for token, colour in (("dark", "#262626"), ("light", "#d0ced0"),
                              ("puce", tile_icons.INKS["dark"]),
                              ("", tile_icons.INKS["dark"])):
            with self.subTest(token=token):
                self.assertEqual(colour, tile_icons.ink_colour(token))

    def test_the_ink_actually_changes_the_pixels(self):
        light_bg = "#ffffff"
        dark = tile_icons.compose("box", light_bg, 512, 0.8, "dark")
        light = tile_icons.compose("box", light_bg, 512, 0.8, "light")
        # Sample the stroke itself: the centre of the box icon's top edge.
        box = ink_box(dark, light_bg)
        x, y = box.x() + box.width() // 2, box.y() + 2
        self.assertEqual("#262626", QtGui.QColor(dark.pixel(x, y)).name())
        self.assertEqual("#d0ced0", QtGui.QColor(light.pixel(x, y)).name())


class DialogTest(unittest.TestCase):
    """Two buttons and a close box: Remove and Accept, the wording Houdini itself uses. There is deliberately no Cancel - closing the window IS cancelling. - That puts the whole contract on `canceled` staying True until one of the two is pressed, and leaves no Cancel button to prove it with, so these tests do."""

    def _dialog(self, current=None):
        dialog = icon_dialog.IconDialog(current)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_category_field_stays_live_on_a_multi_selection(self):
        """Name and Tags grey out where one field cannot say what several rows carry; Category is the opposite - moving a whole selection to one category is the point of it."""
        dialog = icon_dialog.IconDialog(
            None, tile_name="", tile_name_enabled=False,
            categories=["Metal", "Wood"], tile_category="")
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.tile_name_edit.isEnabled(),
                         "the Name field is live on a multi-selection")
        self.assertTrue(dialog.category_combo.isEnabled(),
                        "the Category field greys out, so a selection "
                        "cannot be moved in one go")

    def test_a_blank_category_moves_nothing(self):
        """An empty box is not an answer the way an empty Tags line is: there is no such thing as no category."""
        dialog = icon_dialog.IconDialog(
            None, categories=["Metal"], tile_category="Metal")
        self.addCleanup(dialog.deleteLater)
        dialog.category_combo.setCurrentText("")
        dialog.accept_button.click()
        self.assertIsNone(dialog.new_category)

    def test_a_section_without_categories_shows_no_field(self):
        dialog = self._dialog()
        self.assertIsNone(dialog.category_combo)

    def test_a_stored_underscore_reads_as_its_label(self):
        """`_WIP` shows WIP and opens selected; a move to it reports the stored name."""
        staying = icon_dialog.IconDialog(
            None, categories=["Metal", "_WIP"], tile_category="_WIP")
        self.addCleanup(staying.deleteLater)
        combo = staying.category_combo
        self.assertEqual(["Metal", "WIP"],
                         [combo.itemText(i) for i in range(combo.count())])
        self.assertEqual("WIP", combo.currentText(),
                         "the tile's own category is not the one shown")
        staying.accept_button.click()
        self.assertIsNone(staying.new_category,
                          "an untouched field moved the tile")

        moving = icon_dialog.IconDialog(
            None, categories=["Metal", "_WIP"], tile_category="Metal")
        self.addCleanup(moving.deleteLater)
        moving.category_combo.setCurrentIndex(
            moving.category_combo.findText("WIP"))
        moving.accept_button.click()
        self.assertEqual("_WIP", moving.new_category,
                         "the move names a category nothing stores")

    def test_accept_returns_the_choice(self):
        untouched = self._dialog({"name": "layers", "bg": "#5cc9f5"})
        self.assertTrue(untouched._buttons_by_name["layers"].isChecked(),
                        "the dialog did not open on the tile's own icon")
        untouched.accept_button.click()
        self.assertEqual({"name": "layers", "bg": "#5cc9f5",
                          "ink": "dark"}, untouched.spec)
        dialog = self._dialog({"name": "box", "bg": "#ef8878"})
        dialog._choose("layers")
        dialog._set_bg("#4af2a1")
        dialog.accept_button.click()
        self.assertFalse(dialog.canceled)
        self.assertEqual({"name": "layers", "bg": "#4af2a1",
                          "ink": "dark"}, dialog.spec)

    def _pick(self, dialog, face):
        dialog.face_combo.setCurrentIndex(tile_icons.FACES.index(face))

    def test_the_dialog_opens_on_the_tile_s_face(self):
        dialog = self._dialog({"name": "box", "bg": "#ef8878"})
        self.assertEqual("custom", dialog.face_combo.currentData())
        self._pick(dialog, "preview")
        dialog.accept_button.click()
        self.assertFalse(dialog.canceled)
        self.assertEqual({"face": "preview"}, dialog.spec)
        generic = icon_dialog.IconDialog(None, face="generic")    # Generic is a choice of its own
        self.addCleanup(generic.deleteLater)
        self.assertEqual("generic", generic.face_combo.currentData())
        generic.accept_button.click()
        self.assertEqual({"face": "generic"}, generic.spec)

    def test_only_custom_has_an_icon_and_colours_to_choose(self):
        dialog = self._dialog()
        self.assertEqual("preview", dialog.face_combo.currentData())
        self.assertFalse(dialog._chooser_area.isEnabled(), "the chooser is live on Preview")
        self.assertFalse(dialog.light_toggle.isEnabled())
        self._pick(dialog, "custom")
        self.assertTrue(dialog._chooser_area.isEnabled())
        self.assertTrue(dialog.light_toggle.isEnabled())

    def _item(self, dialog, face):
        return dialog.face_combo.model().item(tile_icons.FACES.index(face))

    def test_preview_is_greyed_where_no_picture_can_exist(self):
        dialog = icon_dialog.IconDialog(None, face="generic", can_preview=False, can_capture=True)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(self._item(dialog, "preview").isEnabled())
        for face in ("capture", "generic", "custom"):
            self.assertTrue(self._item(dialog, face).isEnabled(), "%s greyed with Preview" % face)

    def test_capture_is_greyed_until_the_tile_has_one(self):
        for can_capture in (False, True):
            with self.subTest(can_capture=can_capture):
                dialog = icon_dialog.IconDialog(None, face="generic", can_capture=can_capture)
                self.addCleanup(dialog.deleteLater)
                self.assertEqual(can_capture, self._item(dialog, "capture").isEnabled())
                self.assertTrue(self._item(dialog, "preview").isEnabled(),
                                "a missing capture greyed Preview as well")

    def test_the_icon_menu_reads_render_capture_generic_custom(self):
        """The stored names stay: a library written by an older Amaze keeps its choices."""
        dialog = icon_dialog.IconDialog(None)
        self.addCleanup(dialog.deleteLater)
        combo = dialog.face_combo
        self.assertEqual(["Render", "Capture", "Generic", "Custom"],
                         [combo.itemText(i) for i in range(combo.count())])
        self.assertEqual(["preview", "capture", "generic", "custom"],
                         [combo.itemData(i) for i in range(combo.count())])

    def test_the_preview_square_shows_the_capture(self):
        image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#f59f00"))
        dialog = icon_dialog.IconDialog(None, face="capture", faces={"capture": image},
                                        can_capture=True)
        self.addCleanup(dialog.deleteLater)
        shown = dialog.preview.pixmap().toImage()
        self.assertEqual("#f59f00", shown.pixelColor(shown.width() // 2,
                                                     shown.height() // 2).name())

    def test_the_preview_square_shows_the_chosen_face(self):
        """Preview shows the tile's own picture, Generic the section's face, Custom the composed icon."""
        def solid(colour):
            image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtGui.QColor(colour))
            return image

        dialog = icon_dialog.IconDialog(
            None, faces={"preview": solid("#12b886"), "generic": solid("#1c7ed6")})
        self.addCleanup(dialog.deleteLater)

        def middle():
            shown = dialog.preview.pixmap().toImage()
            return shown.pixelColor(shown.width() // 2, shown.height() // 2).name()

        self.assertEqual("#12b886", middle(), "Preview does not show the tile's picture")
        self.assertTrue(dialog.preview.isEnabled(), "the real face must not draw greyed")
        self._pick(dialog, "generic")
        self.assertEqual("#1c7ed6", middle(), "Generic does not show the section's face")
        self._pick(dialog, "custom")
        self.assertNotIn(middle(), ("#12b886", "#1c7ed6"), "Custom did not compose the icon")

    def test_apply_commits_without_closing(self):
        """Houdini's own pair: Apply commits and stays open, Accept closes. `canceled` stays True after Apply, so a later X re-applies nothing."""
        dialog = self._dialog({"name": "box", "bg": "#ef8878"})
        landed = []
        dialog.applied.connect(lambda: landed.append(dict(dialog.spec)))
        dialog._choose("layers")
        dialog.apply_button.click()
        self.assertEqual([{"name": "layers", "bg": "#ef8878",
                           "ink": "dark"}], landed)
        self.assertTrue(dialog.canceled,
                        "Apply must not read as an accepting close")

    def test_closing_the_window_changes_nothing(self):
        dialog = self._dialog({"name": "box", "bg": "#ef8878"})
        dialog._choose("layers")          # fiddle with it first
        dialog.reject()                   # the X, and Esc
        self.assertTrue(dialog.canceled,
                        "closing the window read as a choice")

    def test_the_light_icon_toggle_reaches_the_choice(self):
        """The Lines dropdown became a switch in the overhaul: off is dark lines, on is light."""
        dialog = self._dialog({"name": "box", "bg": "#262626",
                               "ink": "light"})
        self.assertTrue(dialog.light_toggle.isChecked(),
                        "the dialog did not open on the tile's own ink")
        dialog.light_toggle.setChecked(False)
        dialog.accept_button.click()
        self.assertEqual("dark", dialog.spec["ink"])

    def test_the_chip_wears_the_current_colour_and_the_stack_lines_up(self):
        """The chip beside Custom Color IS the picker and shows the current background; chip and switch pills sit flush LEFT in the stack (the 2026-08-30 redraw, labels after their controls), the buttons flush right."""
        dialog = self._dialog({"name": "box", "bg": "#e0523a"})
        dialog.show()
        self.addCleanup(dialog.hide)
        QtWidgets.QApplication.processEvents()

        self.assertIn("#e0523a", dialog.custom_chip.styleSheet(),
                      "the chip does not wear the current background")
        dialog._set_bg("#b0d1df")
        self.assertIn("#b0d1df", dialog.custom_chip.styleSheet(),
                      "the chip did not follow a preset click")
        self.assertEqual(theme.ui_px(amazetheme.D02_CHIP_W),
                         dialog.custom_chip.width())
        self.assertEqual(    # chip and pill are drawn flush LEFT at the stack's edge, whatever the fonts do
            dialog.custom_chip.mapTo(dialog, QtCore.QPoint(0, 0)).x(),
            dialog.light_toggle.mapTo(dialog, QtCore.QPoint(0, 0)).x(),
            "the chip and the Light Icon pill start at different edges")
        apply_box, accept_box = amazetheme.drawn_repeats(
            "D02", "QPushButton", None)
        self.assertEqual(theme.ui_px(apply_box[2]),
                         dialog.apply_button.width())
        self.assertEqual(theme.ui_px(accept_box[2]),
                         dialog.accept_button.width())
        self.assertEqual(4, len(dialog._swatches),
                         "the overhaul draws FOUR presets plus the chip")

    def test_the_search_filters_without_losing_the_choice(self):
        dialog = self._dialog({"name": "layers", "bg": "#5cc9f5"})
        dialog.search.setText("cloud")
        # isHidden, NOT isVisible: nothing is visible in a dialog never shown, so isVisible answers a different question and reads False for every button either way
        self.assertTrue(dialog._buttons_by_name["layers"].isHidden())
        self.assertFalse(dialog._buttons_by_name["cloud"].isHidden())
        dialog.accept_button.click()
        self.assertEqual("layers", dialog.spec["name"],
                         "filtering changed what was chosen")


class ChooserWearsTheDialogsColoursTest(unittest.TestCase):
    """The icon grid stops being a light island (2026-07-31): the backdrop is the dialog's own window colour and the icons are re-inked in the palette's lightest grey (text_bright, the grey the dialog's labels read in). The trap this guards: Feather SVGs carry stroke="currentColor", QSvgRenderer does not resolve it (recorded), so a straight QIcon(path) draws every icon BLACK - invisible the moment the backdrop went dark."""

    def _dialog(self):
        from amaze.dialogs import icon_dialog
        dialog = icon_dialog.IconDialog(
            {"name": "box", "bg": "#ef8878", "ink": "auto"})
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_backdrop_is_the_dialog_s_own_window_colour(self):
        from amaze.helpers import theme
        dialog = self._dialog()
        window = dialog.palette().color(
            QtGui.QPalette.ColorRole.Window).name()
        holder = dialog._grid.parentWidget().styleSheet()
        area = dialog.findChild(QtWidgets.QScrollArea).styleSheet()
        for sheet, who in ((holder, "grid holder"), (area, "scroll area")):
            self.assertIn(window, sheet,
                          "%s does not wear the dialog's colour" % who)
            self.assertNotIn("#d0ced0", sheet,
                             "%s is the light island again" % who)
        # the checked ring stays unmistakable on the dark backdrop - it is the only indication of the current choice
        self.assertIn(theme.color_hex("text_bright"), holder)

    def test_the_icons_are_re_inked_in_the_lightest_grey(self):
        """Reads the actual pixels of an actual button's icon: at least one pixel of the exact ink, and NO opaque dark pixel anywhere - a black icon is precisely the failure this restyle can cause."""
        from amaze.helpers import theme
        dialog = self._dialog()
        button = dialog._buttons_by_name["box"]
        size = button.iconSize()
        image = button.icon().pixmap(size).toImage()
        self.assertFalse(image.isNull())
        ink = QtGui.QColor(theme.color_hex("text_bright"))
        exact = dark = 0
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() == 0:
                    continue
                if (pixel.red(), pixel.green(), pixel.blue()) == \
                        (ink.red(), ink.green(), ink.blue()):
                    exact += 1
                if pixel.alpha() > 200 and pixel.lightness() < 100:
                    dark += 1
        self.assertGreater(exact, 0, "no pixel carries the ink - the "
                           "icons are not re-inked at all")
        self.assertEqual(0, dark, "opaque dark pixels: the icon is "
                         "drawing in currentColor black on a dark "
                         "backdrop")

    def test_the_icon_pixmaps_carry_their_density(self):
        """The devicePixelRatio contract every pixmap follows (the About-logo lesson): rendered at logical x dpr with the ratio stamped. Driven at ratio 2.0 DIRECTLY - the headless app runs at 1.0, where forgetting the multiply is invisible."""
        from amaze.dialogs import icon_dialog
        pixmap = icon_dialog.IconDialog._chooser_icon(
            "box", 20, 2.0, "#dddddd")
        self.assertEqual(2.0, pixmap.devicePixelRatio(),
                         "the ratio is not stamped - a 2x screen "
                         "paints this half-resolution")
        self.assertEqual(40, pixmap.width(),
                         "not rendered at device pixels")


class MenuWiringTest(unittest.TestCase):
    """Every section's "Edit Icon..." must reach a model and a proxy that actually exist. - This is the test that was missing: the Materials menu shipped calling `self.sorted_model` (the attribute is `material_sorted_ model`) with an unbound `proxy_indexes`, so the flagship section's icon action raised the moment it was clicked. Nothing failed - every unit test passed - because no test drove the menus. - Built against the REAL panel, since the names being checked are panel attributes and a mock would happily answer to anything."""

    SECTIONS = (   # (model attribute, proxy attribute) per section that has tiles - File is ONE entry since the merge and covers hip rows too; Colors keeps its swatch when it has no icon and composes in memory when it has one, a gradient having no id or file
        ("material_model", "material_sorted_model"),
        ("cop_model", "cop_sorted_model"),
        ("code_model", "code_sorted_model"),
        ("file_files_model", "file_sorted_model"),
        ("gradient_model", "gradient_sorted_model"),
    )

    @classmethod
    def setUpClass(cls):
        # the ISOLATED panel - see test_grid_scroll for why a settings-only guard was not enough
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_every_section_ANSWERS_with_models_it_actually_has(self):
        """The typo class this test was built for, one layer up. - The model/proxy pair used to be spelled out inside each of the five right-click handlers, so this read those five call sites out of panel.py by regex - a hand-kept list cannot disagree with the code, which is exactly how `self.sorted_model` shipped in the Materials menu and raised the moment it was clicked. - There is ONE call site now (`Section.menu_customize`), and the pair comes from `tile_models()` on the context - so the question moved with it: not whether this menu names a real attribute, but whether this context answers with real models. Asked of the live panel, because a mock answers to anything."""
        from amaze.panel import sections as sections_mod

        calls = [node for node in ast.walk(ast.parse(
                     inspect.getsource(sections_mod)))
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "edit_tile_icon"]
        self.assertEqual(
            1, len(calls),
            "Customize reaches the shared handler from %d places - it "
            "is one row of one shared tail" % len(calls))

        for key in ("material", "cop", "code", "file", "gradient"):
            with self.subTest(section=key):
                model, proxy = self.panel.sections[key].tile_models()
                self.assertIsNotNone(model, "%s names no model" % key)
                self.assertIsNotNone(proxy, "%s names no proxy" % key)
                self.assertIs(model, proxy.sourceModel(),  # the pair has to be the section's OWN, not whichever models the panel last pointed the shared grid at
                              "%s's proxy is not over its own model" % key)

    def test_every_icon_api_method_takes_the_ARGUMENTS_it_is_called_with(self):
        """`callable` is not the contract - the SIGNATURE is. - The sibling test above passed for months while GradientLibrary.commit_tile_icons was declared `(self)` and the one panel handler called `commit_tile_icons(rows)` on it, which is a TypeError raised after the icon had already been applied in memory. `callable()` cannot see that, and the handler test below patches the method with a MagicMock, which accepts any signature at all (practice.md #338: a mocked handler makes the test vacuous for the thing behind it). - So bind the REAL call shape against the REAL signature."""
        import inspect

        calls = {   # method -> the args the panel handler passes
            "tile_icon":        (0,),
            "set_tile_icon":    (0, {"symbol": "star"}),
            "set_tile_icons":   ([0], {"symbol": "star"}),
            "commit_tile_icons": ([0],),
        }
        checked = 0
        for model_attr, _proxy in self.SECTIONS:
            model = getattr(self.panel, model_attr, None)
            self.assertIsNotNone(model, "the panel has no %s" % model_attr)
            for method, args in calls.items():
                fn = getattr(model, method, None)
                if fn is None:
                    self.assertEqual("commit_tile_icons", method,    # the one optional verb
                                     "%s has no %s()" % (model_attr, method))
                    continue
                try:
                    inspect.signature(fn).bind(*args)
                except TypeError as exc:
                    self.fail(
                        "%s.%s%s does not accept the call the shared "
                        "Customize handler makes: %s"
                        % (model_attr, method,
                           inspect.signature(fn), exc))
                checked += 1
        self.assertTrue(
            checked, "no models were checked - this test proves nothing")

    def test_the_handler_applies_the_dialog_s_choice_to_the_selection(self):
        """Drives edit_tile_icon itself with the dialog stubbed - the step that would have raised on Materials."""
        spec = {"name": "layers", "bg": "#4af2a1", "ink": "dark"}

        class _Signal:
            def __init__(self):
                self.slot = None

            def connect(self, slot):
                self.slot = slot

        class _Dialog:
            canceled = False

            def __init__(self, *a, **k):
                self.spec = spec
                self.finished = _Signal()
                self.applied = _Signal()

            def show(self):
                # the non-modal contract: finished fires after show(), here synchronously so the test stays straight-line
                self.finished.slot()

            def deleteLater(self):
                pass

        for model_attr, proxy_attr in self.SECTIONS:
            model = getattr(self.panel, model_attr)
            proxy = getattr(self.panel, proxy_attr)
            if not model.rowCount():
                continue        # nothing selected-able in this library
            with mock.patch.object(icon_dialog, "IconDialog", _Dialog), \
                    mock.patch.object(type(model), "commit_tile_icons"), \
                    mock.patch.object(type(model), "set_tile_icons") as applied:
                applied.return_value = 0  # commit_tile_icons is patched too: it calls save(), and nothing here may touch real data
                self.panel.edit_tile_icon(
                    model, proxy, [proxy.index(0, 0)])
            self.assertTrue(
                applied.called,
                "%s: Edit Icon did not reach the model" % model_attr)
            self.assertEqual(spec, applied.call_args[0][1])

    def test_every_section_opens_customize_on_its_face(self):
        """Each model answers its face, its picture and its generic art - the dialog shows all three."""
        opened = []

        class _Dialog:
            def __init__(self, *a, **k):
                opened.append(k)
                self.applied = self.finished = mock.Mock()

            def show(self):
                pass

        checked = 0
        for model_attr, proxy_attr in self.SECTIONS:
            model = getattr(self.panel, model_attr)
            proxy = getattr(self.panel, proxy_attr)
            if not model.rowCount():
                continue
            row = proxy.mapToSource(proxy.index(0, 0)).row()
            opened.clear()
            self.panel._icon_dialog = None
            with mock.patch.object(icon_dialog, "IconDialog", _Dialog):
                self.panel.edit_tile_icon(model, proxy, [proxy.index(0, 0)])
            self.panel._icon_dialog = None
            self.assertEqual(1, len(opened), model_attr)
            given = opened[0]
            self.assertEqual(tile_icons.face_for(model, row), given["face"], model_attr)
            self.assertEqual(tile_icons.generic_image(model.tile_face_art(row)),
                             given["faces"]["generic"], model_attr)
            self.assertIn("preview", given["faces"], model_attr)
            self.assertEqual(model.can_preview(row), given["can_preview"], model_attr)
            checked += 1
        self.assertTrue(checked, "no section had a tile - this test proves nothing")


class ComposedCacheTest(unittest.TestCase):
    """The composed-icon cache is capped in BYTES and evicts LRU. - A 240-ENTRY cap sounds bounded until you multiply it by the tile size the user picked: measured ceilings were 63MB at rendersize 256, 252MB at 512 and 1007MB at 1024 - entirely outside the RAM budget the thumbnail engine honours, and the module comment claimed the bound prevented "a gigabyte". - Eviction was also FIFO: it popped the oldest INSERTED entry with no reordering on hit, so past the cap the hottest icons went first and every repaint re-composed them."""

    def setUp(self):
        self._cap = tile_icons._COMPOSED_MAX_BYTES
        self.addCleanup(
            setattr, tile_icons, "_COMPOSED_MAX_BYTES", self._cap)
        self.addCleanup(tile_icons.forget_composed)
        self.names = tile_icons.icon_names()[:12]
        if len(self.names) < 8:
            self.skipTest("icon set unavailable")

    def test_the_cache_stays_within_its_byte_budget(self):
        tile_icons.forget_composed()
        for name in tile_icons.icon_names()[:60]:
            tile_icons.compose(name, "#ef8878", size=1024)
        self.assertLessEqual(
            tile_icons._composed_bytes, tile_icons._COMPOSED_MAX_BYTES,
            "the icon cache grew past its byte budget (%.0f MB)"
            % (tile_icons._composed_bytes / (1024.0 * 1024.0)))

    def test_a_hit_is_not_evicted_first(self):
        """LRU, not FIFO."""
        tile_icons._COMPOSED_MAX_BYTES = 5 * 256 * 256 * 4
        tile_icons.forget_composed()
        for name in self.names[:5]:
            tile_icons.compose(name, "#5cc9f5", size=256)
        oldest = list(tile_icons._composed)[0]
        tile_icons.compose(self.names[0], "#5cc9f5", size=256)   # a HIT
        tile_icons.compose(self.names[5], "#5cc9f5", size=256)   # evicts one
        self.assertIn(
            oldest, tile_icons._composed,
            "the most recently USED entry was evicted first")

    def test_forgetting_resets_the_byte_count(self):
        tile_icons.forget_composed()
        tile_icons.compose(self.names[0], "#4af2a1", size=256)
        self.assertGreater(tile_icons._composed_bytes, 0)
        tile_icons.forget_composed()
        self.assertEqual(0, tile_icons._composed_bytes)


class AnotherSessionsIconsSurviveTest(unittest.TestCase):
    """icons.json was the one library-adjacent JSON file with no stale write handling of any kind: the module cache fills once per path and never re-reads, so a second machine's icon choices were overwritten by the next icon this machine picked."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.path = os.path.join(str(self.prefs.dir),
                                 tile_icons.OVERRIDES_FILE)

    def _behind_our_back(self, key, name):
        with open(self.path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.setdefault("icons", {})[key] = {"name": name, "bg": "#222222"}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

    def test_their_key_survives_our_write(self):
        tile_icons.set_override(self.prefs, "/ours/a.exr",
                                {"name": "layers", "bg": "#111111"})
        self._behind_our_back("/theirs/b.exr", "map")
        tile_icons.set_override(self.prefs, "/ours/c.exr",
                                {"name": "box", "bg": "#333333"})
        with open(self.path, encoding="utf-8") as handle:
            icons = json.load(handle)["icons"]
        self.assertIn("/theirs/b.exr", icons,
                      "the other session's icon choice was overwritten by "
                      "this session's next pick")
        self.assertIn("/ours/a.exr", icons)
        self.assertIn("/ours/c.exr", icons)

    def test_an_in_session_delete_stays_deleted(self):
        """Adoption may only ADD - it must not resurrect the icon this session just removed."""
        tile_icons.set_override(self.prefs, "/ours/a.exr",
                                {"name": "layers", "bg": "#111111"})
        tile_icons.set_override(self.prefs, "/ours/a.exr", {})
        with open(self.path, encoding="utf-8") as handle:
            self.assertNotIn("/ours/a.exr",
                             json.load(handle).get("icons", {}),
                             "removing an icon did not remove it")

    def test_a_write_now_leaves_a_restore_point(self):
        tile_icons.set_override(self.prefs, "/ours/a.exr",
                                {"name": "layers", "bg": "#111111"})
        tile_icons.set_override(self.prefs, "/ours/b.exr",
                                {"name": "map", "bg": "#222222"})
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "icons.json still has no .bak tier - the first bad write is "
            "the last word on every icon in the library")


class CustomColourOpensTheHoudiniPickerTest(unittest.TestCase):
    """The Custom Color button opens the HOUDINI picker like every other colour control - not the OS one, and not a typed field - which is possible only because the dialog is NON-modal, since a native picker under a Qt modal exec loop lands invisible behind it."""

    def _dialog(self):
        from amaze.dialogs import icon_dialog
        return icon_dialog.IconDialog(
            {"name": "box", "bg": "#222222", "ink": "auto"})

    def test_the_button_routes_through_the_shared_picker(self):
        from unittest.mock import patch
        from PySide6 import QtGui
        from amaze.helpers import ui_helpers
        for picked in (QtGui.QColor("#589abb"), None):    # a cancel changes nothing
            with self.subTest(picked=picked):
                dialog = self._dialog()
                before = dialog._bg
                with patch.object(ui_helpers, "pick_color",
                                  return_value=picked) as picker:
                    dialog._pick_custom()
                picker.assert_called_once()
                self.assertEqual(
                    before if picked is None else picked.name(), dialog._bg)

    def test_the_dialog_is_not_modal(self):
        """The load-bearing property: an exec loop here puts the native picker underneath the dialog again."""
        dialog = self._dialog()
        dialog.show()
        self.addCleanup(dialog.hide)
        self.assertFalse(dialog.isModal(),
                         "the icon dialog holds a modal loop again - "
                         "Houdini's picker will open INVISIBLE behind it")


class TheAboutLogoCarriesItsDensityTest(unittest.TestCase):
    """The About logo was scaled to logical pixels with no devicePixelRatio, so on a retina display one rendered pixel drew across two device pixels and the logo appeared at half resolution, because it was; the contract every badge pixmap already follows is device pixels in the image with the ratio stamped on it."""

    def test_the_logo_is_stamped_with_the_apps_ratio(self):
        from PySide6 import QtWidgets
        from amaze.dialogs import prefs_dialog
        prefs_dialog._logo_cache = None          # a fresh render
        image = prefs_dialog._logo_image()
        if image is None:
            self.skipTest("logo asset not renderable here")
        app_ratio = QtWidgets.QApplication.instance().devicePixelRatio()
        self.assertEqual(app_ratio, image.devicePixelRatio(),
                         "the logo does not carry the display's density "
                         "- on any ratio above 1.0 it renders soft")
        from amaze.helpers import theme
        self.assertEqual(max(1, round(theme.ui_px(34) * app_ratio)),
                         image.height(),
                         "the logo's pixel height is not density-scaled")


class TileNameTest(unittest.TestCase):
    """The Customize dialog's Name field (2026-08-01) - the one rename path every section shares, replacing the retired per-section Info renames. Model-level: the write is narrow and reaches disk. Dialog-level: the field obeys the selection law, and a section whose model cannot rename gets no field at all."""

    def test_the_library_rename_is_narrow_and_real(self):
        from amaze.core import library as library_mod
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        if not model.rowCount():
            self.skipTest("fixture library has no rows")
        renamed = model.assets[0].mat_id    # by id: a reload sorts the new name into place
        self.assertTrue(model.set_tile_name(0, "Renamed by test"))
        self.assertEqual("Renamed by test", model.tile_name(0))
        self.assertFalse(model.set_tile_name(0, "   "),
                         "a blank name must be a no-op")
        self.assertFalse(model.set_tile_name(0, "Renamed by test"),
                         "an unchanged name must be a no-op")
        test_support.reset_database_singletons()
        again = library_mod.MaterialLibrary(preferences=prefs_obj)
        self.assertEqual("Renamed by test",
                         again.tile_name(again.find_asset_row_by_id(renamed)),
                         "the rename did not reach disk")

    def test_the_dialog_field_obeys_the_selection_law(self):
        single = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="Rock", tile_name_enabled=True)
        self.assertIsNotNone(single.tile_name_edit,
                             "a renameable tile grows no Name field")
        self.assertTrue(single.tile_name_edit.isEnabled())
        single.tile_name_edit.setText("Stone")
        single._accept()
        self.assertEqual("Stone", single.new_tile_name)
        single.deleteLater()

        multi = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="", tile_name_enabled=False)
        self.assertIsNotNone(multi.tile_name_edit,
                             "the field must grey out, not vanish")
        self.assertFalse(multi.tile_name_edit.isEnabled())
        multi._accept()
        self.assertIsNone(multi.new_tile_name,
                          "a greyed field may not produce a rename")
        multi.deleteLater()

        fileish = icon_dialog.IconDialog(None, 0.0, None)
        self.assertIsNone(fileish.tile_name_edit,
                          "no model rename = no field at all")
        fileish.deleteLater()

    def test_the_window_is_titled_with_the_asset(self):
        """The title band draws the asset's own name; a multi-selection has none, so it keeps the generic one."""
        single = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="Rock", tile_name_enabled=True)
        self.assertEqual("Rock", single.windowTitle())
        single.deleteLater()
        multi = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="", tile_name_enabled=False)
        self.assertEqual("Tile Icon", multi.windowTitle())
        multi.deleteLater()


class AnApplyIsWhatTheNextCommitComparesAgainst(unittest.TestCase):
    """Apply commits and stays open, so a later Accept carries only what changed since."""

    def _applied(self):
        """A rename, a retag and a move, committed by Apply."""
        dialog = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="Brick", tile_name_enabled=True,
            tile_tags="red", categories=["Floors", "Walls"],
            tile_category="Walls")
        self.addCleanup(dialog.deleteLater)
        committed = []
        dialog.applied.connect(lambda: committed.append(
            (dialog.new_tile_name, dialog.new_tags, dialog.new_category)))
        dialog.tile_name_edit.setText("Brick2")
        dialog.tags_edit.setText("red, rough")
        dialog.category_combo.setCurrentIndex(
            dialog.category_combo.findData("Floors"))
        dialog.apply_button.click()
        self.assertEqual([("Brick2", "red, rough", "Floors")], committed,
                         "premise: Apply did not commit the three edits")
        return dialog

    def _accepted(self, dialog):
        dialog.accept_button.click()
        return (dialog.new_tile_name, dialog.new_tags, dialog.new_category)

    def test_an_accept_after_an_apply_commits_nothing_again(self):
        self.assertEqual((None, None, None), self._accepted(self._applied()),
                         "the Accept committed the Apply's values again")

    def test_reverting_after_an_apply_commits_the_revert(self):
        dialog = self._applied()
        dialog.tile_name_edit.setText("Brick")
        dialog.tags_edit.setText("red")
        dialog.category_combo.setCurrentIndex(
            dialog.category_combo.findData("Walls"))
        self.assertEqual(("Brick", "red", "Walls"), self._accepted(dialog),
                         "the Accept wrote the Apply's values over the "
                         "revert")


class TileTagsTest(unittest.TestCase):
    """The Customize dialog's Tags field - a comma-separated line that REPLACES the asset's tags, on EVERY selected row. Live on a multi-selection, like Category and unlike Name."""

    def test_the_library_tag_write_is_narrow_and_real(self):
        from amaze.core import library as library_mod
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        if not model.rowCount():
            self.skipTest("fixture library has no rows")
        self.assertTrue(model.set_tile_tags(0, "metal, rough"))
        self.assertEqual("metal, rough", model.tile_tags(0))
        self.assertFalse(model.set_tile_tags(0, " metal ,rough "),
                         "the same tags spelled with other spacing must "
                         "be a no-op")
        self.assertTrue(model.set_tile_tags(0, ""),
                        "an empty line must CLEAR the tags, not be "
                        "read as no answer")
        self.assertEqual("", model.tile_tags(0))
        test_support.reset_database_singletons()
        again = library_mod.MaterialLibrary(preferences=prefs_obj)
        self.assertEqual("", again.tile_tags(0),
                         "the cleared tags did not reach disk")

    def test_adding_tags_keeps_what_each_row_already_had(self):
        """The multi-selection write: `set_tile_tags` would flatten every row to one line, which is the opposite of what adding means."""
        from amaze.core import library as library_mod
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        if model.rowCount() < 2:
            self.skipTest("fixture library has fewer than two rows")
        model.set_tile_tags(0, "metal")
        model.set_tile_tags(1, "wood")
        self.assertTrue(model.add_tile_tags(0, "rough"))
        self.assertTrue(model.add_tile_tags(1, "rough"))
        self.assertEqual("metal, rough", model.tile_tags(0))
        self.assertEqual("wood, rough", model.tile_tags(1),
                         "adding flattened the row to the shared line")
        self.assertFalse(model.add_tile_tags(0, "rough"),
                         "adding a tag it already has must be a no-op")
        self.assertFalse(model.add_tile_tags(0, ""),
                         "a blank line must add nothing")
        self.assertEqual("metal, rough", model.tile_tags(0))

    def test_the_tags_field_obeys_the_selection_law(self):
        single = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="Rock", tile_name_enabled=True,
            tile_tags="metal")
        self.assertIsNotNone(single.tags_edit,
                             "a taggable tile grows no Tags field")
        self.assertTrue(single.tags_edit.isEnabled())
        single.tags_edit.setText("metal, rough")
        single._accept()
        self.assertEqual("metal, rough", single.new_tags)
        single.deleteLater()

        cleared = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="Rock", tile_name_enabled=True,
            tile_tags="metal")
        cleared.tags_edit.setText("")
        cleared._accept()
        self.assertEqual("", cleared.new_tags,
                         "emptying the field must reach the model as a "
                         "clear, never as None")
        cleared.deleteLater()

        multi = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="", tile_name_enabled=False,
            tile_tags="")
        self.assertIsNotNone(multi.tags_edit,
                             "a taggable tile grows no Tags field")
        self.assertTrue(multi.tags_edit.isEnabled(),
                        "Tags greys on a multi-selection; it must stay "
                        "editable, like Category and unlike Name")
        self.assertEqual("", multi.tags_edit.text(),
                         "a multi-selection must open with an EMPTY tag "
                         "field - there is no one line that says what "
                         "several rows carry")
        multi.tags_edit.setText("metal")
        multi._accept()
        self.assertEqual("metal", multi.new_tags,
                         "what is typed on a multi-selection must reach "
                         "every selected row")
        multi.deleteLater()

        untouched = icon_dialog.IconDialog(
            None, 0.0, None, tile_name="", tile_name_enabled=False,
            tile_tags="")
        untouched._accept()
        self.assertIsNone(untouched.new_tags,
                          "an untouched multi-selection field must add "
                          "nothing, never clear every row")
        untouched.deleteLater()

        fileish = icon_dialog.IconDialog(None, 0.0, None)
        self.assertIsNone(fileish.tags_edit,
                          "a model with no tags = no field at all")
        fileish.deleteLater()

    def test_the_panel_applies_a_cleared_field(self):
        """`new_tags` is harvested as "" for a clear, so the apply site must test `is not None` - a truth test drops exactly the clear."""
        source = inspect.getsource(panel_mod.AmazePanel.edit_tile_icon)
        tree = ast.parse(textwrap.dedent(source))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "set_tile_tags"]
        self.assertTrue(calls, "the dialog's tags never reach the model")
        guards = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Compare)
                  and isinstance(node.left, ast.Name)
                  and node.left.id == "new_tags"
                  and any(isinstance(op, ast.IsNot) for op in node.ops)
                  and any(isinstance(c, ast.Constant) and c.value is None
                          for c in node.comparators)]
        self.assertTrue(guards,
                        "the tags apply is not guarded by `new_tags is "
                        "not None` - an empty field will never clear "
                        "the tags")


class OneRowsIconCostsOneRowsLookups(unittest.TestCase):
    """set_tile_icon refreshes ONE row - a full rebuild per call made a multi-select icon pass O(rows^2) in store lookups, each a deepcopy."""

    def test_set_tile_icon_does_not_walk_every_row(self):
        from unittest import mock

        from amaze.core import library as library_mod
        from amaze.core import tile_icons
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        if model.rowCount() < 3:
            self.skipTest("fixture library has too few rows")
        calls = []
        real = tile_icons.override_for

        def counted(preferences, mat_id):
            calls.append(mat_id)
            return real(preferences, mat_id)

        with mock.patch.object(tile_icons, "override_for", counted):
            model.set_tile_icon(model.index(0, 0),
                                {"name": "circle", "bg": "#e0523a",
                                 "ink": "dark"}, save=False)
        self.assertLess(
            len(calls), model.rowCount(),
            "one row's icon walked the whole model: %d lookups over %d "
            "rows, each a store get with a deepcopy"
            % (len(calls), model.rowCount()))

    def test_a_rebuild_asks_each_row_s_icon_once(self):
        from amaze.core import library as library_mod
        from amaze.core import tile_icons
        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        self.assertTrue(model.set_tile_icon(0, {"name": "circle",
                                                "bg": "#e0523a"}))
        paths, keys = list(model._mat_paths), list(model._row_keys)
        calls = []
        real = tile_icons.override_for

        def counted(preferences, key):
            calls.append(key)
            return real(preferences, key)

        with mock.patch.object(tile_icons, "override_for", counted):
            model.rebuild_thumbs()
        self.assertEqual(model.rowCount(), len(calls),
                         "a rebuild of %d rows read the icon store %d times"
                         % (model.rowCount(), len(calls)))
        self.assertEqual((paths, keys),
                         (model._mat_paths, model._row_keys),
                         "the rebuilt maps differ from the per-row ones")


class AnIconEditWritesNoIndex(unittest.TestCase):
    """An icon lives in its own store, so choosing one writes no record list, and touches one row."""

    SPEC = {"name": "circle", "bg": "#e0523a", "ink": "dark"}

    def setUp(self):
        from amaze.core import library as library_mod
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.library_mod = library_mod

    def _saves_during(self, action):
        from amaze.core import database
        with mock.patch.object(database.DatabaseConnector, "save",
                               autospec=True,
                               side_effect=database.DatabaseConnector.save) as save:
            action()
        return save.call_count

    def test_the_panel_s_icon_pass_saves_no_index(self):
        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        rows = list(range(model.rowCount()))

        def icon_pass():
            for row in rows:
                self.assertTrue(model.set_tile_icon(row, self.SPEC, save=False))
            model.commit_tile_icons(rows)

        self.assertEqual(0, self._saves_during(icon_pass),
                         "an icon choice wrote the material list, whose "
                         "records no icon field lives in")
        self.assertTrue(model.tile_icon(0), "premise: the icon landed")

    def test_a_colour_icon_saves_no_index(self):
        from amaze.core import gradient_library
        model = gradient_library.GradientLibrary(self.prefs)
        model.add_user_gradient(
            "Icon Probe", "Uncategorized",
            {"keys": [0.0, 1.0], "values": [[1, 0, 0], [0, 0, 1]],
             "bases": ["Linear", "Linear"]})
        self.assertTrue(model.rowCount(), "premise: a palette was saved")
        self.assertEqual(
            0, self._saves_during(lambda: model.set_tile_icon(0, self.SPEC)),
            "a palette's icon wrote the Colors list")

    def test_one_row_s_icon_scans_no_other_row_and_reads_no_ledger(self):
        from amaze.core import versions
        model = self.library_mod.MaterialLibrary(preferences=self.prefs)

        class Counted(dict):
            scanned = 0

            def items(self):
                Counted.scanned += len(self)
                return dict.items(self)

        model._thumb_rows = Counted(model._thumb_rows)
        with mock.patch.object(versions, "record_render",
                               wraps=versions.record_render) as ledger:
            self.assertTrue(model.set_tile_icon(1, self.SPEC, save=False))
        self.assertEqual(0, Counted.scanned,
                         "one row's icon scanned every row's thumbnail key")
        ledger.assert_not_called()
        key = model._thumb_key(1)
        self.assertEqual(1, model._thumb_rows.get(key),
                         "the row's new picture key does not lead back to it")
        self.assertEqual([1], [row for row in model._thumb_rows.values()
                               if row == 1], "the row's old key was kept")


class TheLineWeightRedrawsEverySection(unittest.TestCase):
    """Look > Tile Icon Line reaches every section with tile icons, Colors included."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        from amaze.dialogs import prefs_dialog
        prefs = self.panel.prefs
        self.addCleanup(setattr, prefs, "icon_line_weight",
                        prefs.icon_line_weight)
        prefs.icon_line_weight = "template"
        self.dialog = prefs_dialog.PrefsDialog(prefs, panel=self.panel)
        self.addCleanup(self.dialog.deleteLater)

    def set_weight(self, token):
        combo = self.dialog._combo_icon_weight
        combo.setCurrentIndex(combo.findData(token))
        self.assertEqual(token, self.panel.prefs.icon_line_weight)

    def test_every_section_with_tile_icons_is_redrawn(self):
        asked = []
        models = {key: section.tile_models()[0]
                  for key, section in self.panel.sections.items()}
        self.assertNotIn(None, models.values(), "premise: every section has tiles")
        with contextlib.ExitStack() as stack:
            for key, model in models.items():
                stack.enter_context(mock.patch.object(
                    model, "rerender_tile_icons", create=True,
                    side_effect=lambda key=key: asked.append(key)))
            self.set_weight("feather")
        self.assertEqual(sorted(models), sorted(asked),
                         "a section's tile icons kept the old line weight")

    def test_a_colour_tile_with_an_icon_repaints_at_the_new_weight(self):
        model = self.panel.gradient_model
        self.assertTrue(model.rowCount(), "premise: the fixture has palettes")
        self.assertTrue(model.set_tile_icon(0, {"name": "layers",
                                                "bg": "#4af2a1"}))
        self.addCleanup(model.set_tile_icon, 0, {})
        index = model.index(0, 0)
        thin = model.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        repainted = []

        def heard(top, bottom, _roles=()):
            repainted.append((top.row(), bottom.row()))

        model.dataChanged.connect(heard)
        self.addCleanup(model.dataChanged.disconnect, heard)
        self.set_weight("feather")
        self.assertTrue(any(top <= 0 <= bottom for top, bottom in repainted),
                        "the Colors tile was never told to repaint")
        bold = model.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertNotEqual(thin, bold,
                            "the Colors tile serves its cached picture at "
                            "the old line weight")


class AnIconOverASelectionWritesOnce(unittest.TestCase):
    """The shared Customize apply commits `icons.json` once per gesture, and every row still lands."""

    SPEC = {"name": "circle", "bg": "#e0523a", "ink": "dark"}

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_every_section_commits_a_selection_s_icon_once(self):
        from amaze.helpers import hostos
        self.panel.section_tabs.setChecked("file")    # File lists its rows once shown
        QtWidgets.QApplication.processEvents()
        checked = []
        for attr, _proxy in MenuWiringTest.SECTIONS:
            model = getattr(self.panel, attr)
            rows = list(range(model.rowCount()))
            if len(rows) < 2:
                continue
            with self.subTest(model=attr):
                writes = []
                real = hostos.write_json_atomic

                def counted(path, *args, writes=writes, **kwargs):
                    if os.path.basename(path) == tile_icons.OVERRIDES_FILE:
                        writes.append(path)
                    return real(path, *args, **kwargs)

                with mock.patch.object(hostos, "write_json_atomic", counted):
                    self.panel._apply_icon_spec(model, rows, self.SPEC)
                self.assertEqual(1, len(writes), "%s wrote %s %d times for "
                                 "one gesture" % (attr, tile_icons.OVERRIDES_FILE,
                                                  len(writes)))
                self.assertEqual([tile_icons.normalise(self.SPEC)] * len(rows),
                                 [model.tile_icon(row) for row in rows],
                                 "%s: a row did not take the icon" % attr)
                checked.append(attr)
        self.assertIn("material_model", checked, "premise: Materials checked")
        self.assertIn("file_files_model", checked, "premise: File checked")


if __name__ == "__main__":
    unittest.main()
