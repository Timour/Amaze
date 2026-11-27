"""Customize as a dialog window: a view of `pane.customize.Customize` in Houdini's QML controls."""

from PySide6 import QtCore

import amaze
from amaze import amazetheme, tooltips
from amaze.core import tile_icons
from amaze.pane import customize
from amaze.qml import dialog_window, pictures

CUSTOMIZE_QML = amaze.package_file("ui", "dialogs", "CustomizeWindow.qml")
FRAME = "D02"    # the window as its design frame draws it
PREVIEW = "amazecustomize"    #: image://amazecustomize/<n>: the preview, n counting each picture


class PreviewPictures(pictures.StatePictures):
    """`image://amazecustomize/<n>`: the preview, as the Customize engine gives it."""

    def picture(self, key: str):
        return self._state.preview_image()


class CustomizeState(dialog_window.DialogState):
    """What Customize's QML shows of its `Customize` engine, and the slots its controls call."""

    drawn: dict = {}    # `amazetheme.drawn_customize`
    words: dict = {}
    tips: dict = {}
    categories: list = []    # the Category menu's rows, as {text, value: its key}
    categoryRow: int = -1
    faces: list = []    # the Image menu's rows, as {text, value, enabled}
    faceRow: int = 0
    custom: bool = False    # a custom icon is chosen: only then are its icon and colours live
    icon: str = ""    # the icon chosen
    light: bool = False
    background: str = ""
    presets: list = []    # the preset colours, as {text, value: the colour}
    icons: list = []    # the icons the search lists
    preview: str = ""    # the engine's picture as a `PREVIEW` url, "" for none

    def __init__(self, question, **kwargs) -> None:
        chosen = question    # the window's `Customize` engine
        super().__init__(question={"name": chosen.name or "", "hasName": chosen.name is not None,
                                   "nameEnabled": chosen.name_enabled, "tags": chosen.tags or "",
                                   "hasTags": chosen.tags is not None,
                                   "hasCategory": bool(chosen.categories)}, **kwargs)
        self._customize = chosen
        chosen.setParent(self)    # Qt deletes it with the window
        self._pictures = 0    # the previews shown, which gives each its own url
        self.drawn = amazetheme.drawn_customize(FRAME)
        self.words = {"name": amazetheme.LABEL_NAME, "category": amazetheme.LABEL_CATEGORY,
                      "tags": amazetheme.LABEL_TAGS, "image": amazetheme.LABEL_ICON,
                      "light": amazetheme.LABEL_LIGHT_ICON, "colour": amazetheme.LABEL_CUSTOM_COLOR,
                      "search": amazetheme.PLACEHOLDER_SEARCH_ICONS, "apply": amazetheme.BTN_APPLY,
                      "accept": amazetheme.BTN_ACCEPT}
        self.tips = {"name": tooltips.CUSTOMIZE_TILE_NAME, "category": tooltips.CUSTOMIZE_CATEGORY,
                     "tags": chosen.tags_tip, "image": tooltips.CUSTOMIZE_ICON,
                     "light": tooltips.CUSTOMIZE_LIGHT_ICON, "colour": tooltips.CUSTOMIZE_CUSTOM_COLOR}
        self.categories, self.categoryRow = dialog_window.menu_rows(chosen.categories, chosen.category)
        self.faces = [{"text": label, "value": face, "enabled": offered}
                      for face, label, offered in chosen.faces]
        self.presets = [{"text": label, "value": colour} for label, colour in tile_icons.PRESETS]
        chosen.changed.connect(self._show_choices)
        chosen.listed.connect(self._show_icons)
        self._show_choices()
        self._show_icons()

    def _show_choices(self) -> None:
        """The engine's face, icon and colours, and its preview under a url of its own."""
        chosen = self._customize
        self.faceRow = [face for face, _label, _offered in chosen.faces].index(chosen.face)
        self.custom, self.icon = chosen.is_custom(), chosen.icon
        self.light, self.background = chosen.is_light(), chosen.background
        self._pictures += 1
        self.preview = "image://%s/%d" % (PREVIEW, self._pictures) if chosen.preview() is not None else ""

    def _show_icons(self) -> None:
        self.icons = list(self._customize.icons)

    def preview_image(self):
        """The engine's preview, a QImage or None."""
        return self._customize.preview()

    @QtCore.Slot(str)
    def chooseFace(self, face: str) -> None:
        """A row of the Image menu picked; one the engine does not take leaves the menu on its row."""
        self._customize.set_face(face)
        if self._customize.face != face:    # Qt's menu steps onto a greyed row by key
            self.faceRowChanged.emit()

    @QtCore.Slot(str)
    def chooseIcon(self, name: str) -> None:
        self._customize.choose_icon(name)

    @QtCore.Slot(bool)
    def setLight(self, on: bool) -> None:
        self._customize.set_light(on)

    @QtCore.Slot(str)
    def setBackground(self, colour: str) -> None:
        self._customize.set_background(colour)

    @QtCore.Slot()
    def pickColour(self) -> None:
        self._customize.pick_colour()

    @QtCore.Slot(str)
    def search(self, text: str) -> None:
        self._customize.search(text)


class CustomizeWindow(dialog_window.DialogWindow):
    """Customize: the fields, the picture and a custom icon's parts, the icons, Apply and Accept."""

    STATE = CustomizeState
    SOURCE_URL = QtCore.QUrl.fromLocalFile(CUSTOMIZE_QML).toString()
    DEFAULT_SIZE = QtCore.QSize(*amazetheme.DIALOG_LAYOUT[FRAME]["frame"])    # which it grows from
    MINIMUM_SIZE = DEFAULT_SIZE

    def setupEngine(self) -> None:
        super().setupEngine()
        self.engine().addImageProvider(PREVIEW, PreviewPictures(self.sharedState()))


def ask(owner, question, apply) -> CustomizeWindow:
    """Customize for a CustomizeQuestion: each commit calls `apply(CustomizeAnswer)`."""
    chosen = customize.Customize(question, apply, owner.ask_colour)

    def committed(fields):
        if fields is not None:    # Apply, or Accept once the window has closed; None is a close
            chosen.commit(str(fields["name"]), str(fields["tags"]), str(fields["category"]))
    return CustomizeWindow.ask(owner, chosen.title, chosen, committed)
