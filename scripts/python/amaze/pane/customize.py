"""Customize's choices and rules for either host's window: what it shows, what a commit writes."""

from PySide6 import QtCore

from amaze import amazetheme, tooltips
from amaze.core import tile_icons
from amaze.pane import asks

COLOUR_TITLE = "Tile Background"    # the colour picker's title
PREVIEW_PX = 256    # the size a custom icon is composed at for the preview


class Customize(QtCore.QObject):
    """One Customize window's question, the face, icon and colours chosen in it, and its commits."""

    changed = QtCore.Signal()    # the face, the icon or a colour: the preview is another picture
    listed = QtCore.Signal()    # the search lists other icons

    def __init__(self, question, apply, ask_colour, parent=None) -> None:
        super().__init__(parent)
        self._apply = apply    # the asker's: called at each commit, True when it wrote the answer
        self._ask_colour = ask_colour    # the host's `ask_colour`
        self._pictures = dict(question.faces or {})    # {face: image} for the preview
        self._stroke = question.stroke or tile_icons.STROKE_UNITS
        current = tile_icons.normalise(question.icon)
        self.title = (question.tile_name if question.tile_name and question.tile_name_enabled
                      else amazetheme.TITLE_TILE_ICON)    # several tiles have no one name to show
        self.name = question.tile_name    # as last committed; None: the window has no Name field
        self.name_enabled = bool(question.tile_name_enabled)    # off for several tiles
        self.tags = question.tile_tags    # as last committed; None: no Tags field
        self.tags_tip = (tooltips.CUSTOMIZE_TAGS_ONE_TILE if self.name_enabled
                         else tooltips.CUSTOMIZE_TAGS_MANY_TILES)    # several tiles: the tags are added
        self.category = question.tile_category or ""    # as last committed; "" for mixed or none
        self.categories = list(question.categories or [])    # (key, name) rows; empty: no field
        if self.categories and (not self.category or self.category not in dict(self.categories)):
            self.categories.insert(0, ("", ""))    # an empty first row, which changes no category
        self.faces = tuple(    # the Image menu's rows: (face, label, whether it can be chosen)
            (face, label, face != "image" or bool(question.can_preview))
            for face, label in zip(tile_icons.FACES, amazetheme.FACE_LABELS))
        self.face = question.face if question.face in tile_icons.FACES else tile_icons.face_of(current)
        self.icon = current.get("name", "") or "box"
        self.background = current.get("bg", "") or tile_icons.PRESETS[0][1]
        self.ink = current.get("ink", "") or tile_icons.DEFAULT_INK
        self.icons = list(tile_icons.icon_names())    # the icons listed: those the search matches

    def is_custom(self) -> bool:
        """Only a custom icon has an icon and colours to choose."""
        return self.face == "custom"

    def is_light(self) -> bool:
        """Whether the icon's lines are the light ink, for a dark background."""
        return self.ink == "light"

    def set_face(self, face: str) -> None:
        """Another row of the Image menu; one that cannot be chosen is not taken."""
        if face != self.face and any(face == row[0] and row[2] for row in self.faces):
            self.face = face
            self.changed.emit()

    def choose_icon(self, name: str) -> None:
        if name != self.icon:
            self.icon = name
            self.changed.emit()

    def set_background(self, colour: str) -> None:
        """A colour the composer can use becomes the background; any other is not taken."""
        if colour != self.background and tile_icons.is_valid_colour(colour):
            self.background = colour
            self.changed.emit()

    def set_light(self, on: bool) -> None:
        ink = "light" if on else "dark"
        if ink != self.ink:
            self.ink = ink
            self.changed.emit()

    def pick_colour(self) -> None:
        """The host's picker on the background; a view must not be modal. ▸r/houdini-colour-picker"""
        self._ask_colour(self.background, COLOUR_TITLE,
                         lambda colour: colour is not None and self.set_background(colour))

    def search(self, text: str) -> None:
        """List the icons whose name contains `text`; every icon for no text."""
        text = (text or "").strip().lower()
        icons = [name for name in tile_icons.icon_names() if text in name]
        if icons != self.icons:
            self.icons = icons
            self.listed.emit()

    def preview(self):
        """The picture of the face chosen, a QImage: a row with no picture yet shows the generic one."""
        if self.is_custom():
            return tile_icons.compose(self.icon, self.background, PREVIEW_PX, self._stroke, self.ink)
        return self._pictures.get(self.face) or self._pictures.get("generic")

    def answer(self, name: str = "", tags: str = "", category: str = "") -> asks.CustomizeAnswer:
        """What a commit writes for the fields as typed: None for one absent, off, blank or unchanged."""
        if self.is_custom():
            spec = tile_icons.normalise({"name": self.icon, "bg": self.background, "ink": self.ink})
        else:
            spec = {"face": self.face}    # the model stores it only where it is not the default
        name, tags = name.strip(), tags.strip()
        renames = self.name is not None and self.name_enabled and name and name != self.name
        retags = self.tags is not None and tags != self.tags.strip()    # an empty field clears the tags
        moves = self.categories and category and category != self.category.strip()
        return asks.CustomizeAnswer(spec=spec, name=name if renames else None,
                                    tags=tags if retags else None, category=category if moves else None)

    def commit(self, name: str = "", tags: str = "", category: str = "") -> asks.CustomizeAnswer:
        """Apply or Accept: the asker gets the edits; the next commit compares against those it wrote."""
        answer = self.answer(name, tags, category)
        if not self._apply(answer):
            return answer    # refused: nothing was written, so the next commit hands on the same edits
        if answer.name is not None:
            self.name = answer.name
        if answer.tags is not None:
            self.tags = answer.tags
        if answer.category is not None:
            self.category = answer.category
        return answer
