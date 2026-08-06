"""
Holds useful UI Elements
"""

import collections
import contextlib
import os

from PySide6 import QtWidgets, QtCore, QtGui, QtSvg, QtSvgWidgets

from amaze.core import debug, grid_columns
from amaze.helpers import theme


@contextlib.contextmanager
def relayout(*models):
    """Wrap a WHOLESALE change to one or more models' contents.

    `layoutAboutToBeChanged` promises every attached view that the
    mapping from index to item is about to change and that
    `layoutChanged` will say when it is safe again. If something
    raises between the two, that promise is never kept: the views stay
    mid-layout-change for the rest of the session, and their persistent
    indexes are never restored.

    Twenty-odd sites opened that pair by hand, none of them in a
    `finally` - recorded as a batch 10 item and taken here because the
    sidebar's category verbs are three of them. A rename that raises
    on the second of two categories used to leave the panel in that
    state.

    NOT for a structural insert or removal: `removeRow` and friends
    emit the real begin/endRemoveRows contract, and layering a
    layout-change pair around one hands the proxy dangling persistent
    indexes at the closing signal - a native segfault, crashed H21
    (sections.py `delete_rows` says so).
    """
    live = [model for model in models if model is not None]
    for model in live:
        model.layoutAboutToBeChanged.emit()
    try:
        yield
    finally:
        # Reverse order, so the innermost model is released first -
        # the mirror of how they were announced.
        for model in reversed(live):
            model.layoutChanged.emit()


# The drag "name tag" - black rectangle, white text. Shared by BOTH the
# black self-managed drag's floating label (cop/color/code) AND the
# native drags' pixmap (materials), so every drag looks identical even
# though the mechanisms differ - "native" is only the drop mechanism,
# the picture is a separate choice.
DRAG_TAG_STYLE = (
    "background-color: #2d2d2d; color: #e6e6e6;"
    " border: 1px solid #555555; padding: %dpx %dpx;"
    % (theme.ui_px(2), theme.ui_px(8))
)


def name_tag_pixmap(name: str) -> QtGui.QPixmap:
    """The black-rectangle/white-text drag tag as a PIXMAP - the drag
    picture for the native drags (materials, and textures/geometry if
    wanted), matching the black system's floating label via the shared
    DRAG_TAG_STYLE."""
    label = QtWidgets.QLabel(str(name))
    label.setStyleSheet(DRAG_TAG_STYLE)
    label.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
    label.adjustSize()
    label.ensurePolished()
    return label.grab()


def ui_asset(name: str) -> str:
    """The absolute path of a ui/ asset.

    $AMAZE FIRST, deliberately. It is not merely a convenience: saved
    assets on disk carry literal "$AMAZE/..." parameter values, so the
    variable is a contract with the user's data and the plugin resolves
    its own resources the same way. Every other asset lookup in the
    codebase already goes through it.

    The module-relative fallback exists only for the case where it is
    genuinely undefined - tests, and the pure-python offline tools that
    run without hou (__init__.py guards for exactly that). It is a
    fallback rather than the rule, because preferring it would let a
    dev-tree module and an installed $AMAZE disagree silently.
    """
    root = ""
    try:
        import hou
        root = hou.getenv("AMAZE") or hou.getenv("ASSETLIB") or ""
    except Exception:                                    # noqa: BLE001
        root = ""
    if root:
        candidate = os.path.join(
            root, "scripts", "python", "amaze", "ui", name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", name)


def live_current_index(view):
    """A view's current index, RE-DERIVED from its live model, or None.

    NEVER read a stored QModelIndex through a proxy. `isValid()` checks
    only that an index has a row, a column and a non-null model pointer -
    it does NOT check that the proxy's internal row mapping still
    contains that index. Reset a QSortFilterProxyModel and a held index
    keeps reporting isValid() True while `proxy_to_source` dereferences
    a mapping that has been freed.

    That is not a theoretical risk: it took Houdini down on 2026-07-29
    at 00:13. A section-tab click reached _capture_section_state, which
    called `.data()` on the sidebar's stored currentIndex, and the crash
    log's top three frames are QSortFilterProxyModel::data ->
    mapToSource -> proxy_to_source, signal 11. Nothing reached the debug
    log, because a SIGSEGV is not a Python exception - @debug.guarded
    cannot catch it and neither can `except`. The ONLY defence is to not
    create the condition.

    The likely resetter is a background result landing while the panel
    is idle: thumbnail and catalogue workers hand their results back via
    QTimer.singleShot(0, ...), so a model refresh can run between any
    two GUI operations, including 42 minutes after the last click.

    So: check the index still belongs to the model the view is showing
    NOW, bounds-check it against the CURRENT row and column counts, then
    hand back a FRESH index built by that model. `index.model()` and
    `isValid()` are both safe on a stale index - they read stored
    values and dereference nothing.
    """
    if view is None:
        return None
    model = view.model()
    if model is None:
        return None
    index = view.currentIndex()
    if not index.isValid():
        return None
    # The index may predate a model swap entirely (a section switch
    # rebuilds these views), in which case it belongs to a model this
    # view no longer shows - and mapping it through the current proxy is
    # the bug the drag path already hit once, where an ONLINE index read
    # through the MATERIAL proxy dragged whichever local material sat at
    # that row.
    if index.model() is not model:
        return None
    # ROW ONLY, and NEVER columnCount. Probed on PySide6 / 22.0.395:
    # on a QAbstractListModel subclass `columnCount` is a PRIVATE method
    # and is not callable at all - with a parent it raises "columnCount(
    # const QModelIndex &parent) const is a private method", without one
    # it raises "takes exactly one argument (0 given)". The first shipped
    # version of this helper called it bare, so every switch to a section
    # whose sidebar is a plain list model rather than a proxy threw
    # "TextureFolders.columnCount() takes exactly one argument (0 given)"
    # - eight times across two sessions before the log was read.
    #
    # Not needed anyway: the column of a view's own currentIndex came
    # FROM this model, so it is in bounds by construction, and isValid()
    # already guarantees it is >= 0. Only the row can be out of range,
    # and rowCount takes an explicit parent on both a C++ proxy and a
    # Python model.
    try:
        rows = model.rowCount(QtCore.QModelIndex())
    except TypeError:
        # A model with some other signature. Refusing is safe: the
        # caller's fallback is "no selection", never a wrong one.
        return None
    if index.row() >= rows:
        return None
    # COLUMN 0, not the clicked cell: over the list-mode table the
    # current index keeps whichever visible column the click landed on
    # (research.md > Row selection over a table view), and the grid
    # models answer roles only on the owning column - every caller here
    # reads roles or rows, so the clicked cell's column is never the
    # answer.
    return model.index(index.row(), 0)


def _screen_dpr() -> float:
    """The primary screen's device-pixel ratio, 1.0 when headless.

    Tooltips are built at setToolTip time, before anyone knows which
    monitor they will pop on, so the primary screen stands in for all
    of them.
    """
    from PySide6 import QtGui as _QtGui

    screen = _QtGui.QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    return float(screen.devicePixelRatio()) or 1.0


def tooltip_text(text: str, max_px: int = 800) -> str:
    """A tooltip that never draws wider than max_px REAL screen pixels.

    Qt renders a PLAIN-text tooltip as one line however long - a
    sentence of help became a black bar across the whole screen. Rich
    text wraps, and a width-capped table is the one rich-text width
    control QTextDocument actually honours. Short strings pass through
    untouched: a needlessly rich short tooltip re-styles for nothing.

    The cap is measured in DEVICE pixels, a ruler on a screenshot:
    Qt's own units are logical, which a Retina screen doubles, so a
    logical-px cap of 800 drew 1600 real pixels wide and a ~720-logical
    sentence slipped under it as one screen-crossing line (live report
    2026-07-31).
    """
    from PySide6 import QtWidgets as _QtWidgets

    cap = max(1, int(max_px / _screen_dpr()))
    metrics = QtGui.QFontMetrics(_QtWidgets.QToolTip.font())
    if metrics.horizontalAdvance(text) <= cap:
        return text
    import html

    # Rich text eats newlines - the multi-paragraph tooltips keep
    # their breaks or they become one undifferentiated wall.
    body = html.escape(text).replace("\n", "<br>")
    return '<qt><table width="%d"><tr><td>%s</td></tr></table></qt>' % (
        cap, body)


def render_svg_pixmap(path, size, color_replacements=None):
    """Renders an SVG file onto a transparent square QPixmap, optionally
    swapping literal color strings in the SVG text first (the icon assets
    bake tint-target hexes like #5d7abd for exactly this). QSvgRenderer
    straight onto our own transparent-filled pixmap, never QIcon's own
    SVG engine - that engine's internal rasterization produced an opaque
    black background even onto a transparent destination. Returns a
    blank transparent pixmap if the file is missing, so callers
    degrade gracefully."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for old, new in (color_replacements or {}).items():
            text = text.replace(old, new)
        painter = QtGui.QPainter(pixmap)
        QtSvg.QSvgRenderer(QtCore.QByteArray(text.encode("utf-8"))).render(painter)
        painter.end()
    return pixmap


class DesignedDialog(QtWidgets.QDialog):
    """A dialog in the shape his HTML designs describe.

    First one built from an HTML handover (the Versions pop-up,
    2026-08-02). The shell is here rather than in the one dialog that
    needed it because the SHAPE is the design language, not this
    dialog: a dark header band carrying an icon, a small subtitle, a
    big bold title and a kind line, over a body column inset equally
    on both sides, ending in two buttons that fill that column.

    NUMBERS ARE HIS, taken from the page and stated once here:

        frame          512 x 435
        header band    512 x 132        #22232b
        body                            #2b2c35
        icon           60 x 60 at 33,36
        subtitle       23px  at 131,15  #93b9e7
        title          32px bold 131,47 #dddcdd
        kind           23px  at 131,88  #93b9e7
        body column    inset 35 both sides -> 442 wide
        field          442 x 60         #3e3f4a
        buttons        202 x 42, gap 38 #3e3f4a, radius 10, 23px

    NOT THROUGH theme.ui_px. Everything else in the panel scales by
    Houdini's UI scale factor, which is 2.0 on his machine - so a 512
    design opened at 1024 and he said so immediately. He asked for a
    FIXED 512 x 435 window, and a design given in final pixels is
    final: scaling it would be the panel overruling the design.

    The sizes are in PIXELS and go straight across: he designs in
    Source Sans 3 because it matches Houdini's own UI font, so a 23px
    label in the design is a 23px label here (practice.md). The
    colours are literal for the same reason - they are the design's
    answer, not an approximation of a theme token.
    """

    FRAME = (512, 435)
    HEADER_H = 132
    INSET = 35
    HEADER_BG = "#22232b"
    BODY_BG = "#2b2c35"
    FIELD_BG = "#3e3f4a"
    LABEL_INK = "#93b9e7"
    TITLE_INK = "#dddcdd"
    FIELD_H = 60
    BUTTON = (202, 42)
    BUTTON_GAP = 38
    RADIUS = 10
    SUBTITLE_PX, TITLE_PX, KIND_PX, LABEL_PX, BUTTON_PX = 23, 32, 23, 20, 23

    @staticmethod
    def d(value):
        """One of HIS pixels, in the logical pixels Qt sizes with.

        His pages are drawn on a Retina screen, so a number in the
        design is a DEVICE pixel - and Qt sizes widgets in logical
        pixels, two device pixels each here. Taken literally, a 512
        design opened at 1024 device pixels: twice the size he asked
        for, which is what he saw.

        The unstyled dropdown is what proved it. It was the one
        control whose size came from Houdini rather than from me, and
        it was right while everything around it was double - "the text
        in the drop down seems correct its smaller than the rest".

        NOT theme.ui_px, which is a different question: that applies
        Houdini's own UI-scale preference to the panel's chrome, and
        on this machine it is 1.0 because Qt is already doing the
        scaling. This converts his units into Qt's.
        """
        try:
            screen = QtGui.QGuiApplication.primaryScreen()
            ratio = float(screen.devicePixelRatio()) if screen else 1.0
        except Exception:                                 # noqa: BLE001
            ratio = 1.0
        if ratio <= 1.0:
            return value
        scaled = value / ratio
        return scaled if isinstance(value, float) else int(round(scaled))

    def __init__(self, parent=None, title="", subtitle="", kind="",
                 icon="") -> None:
        super().__init__(parent)
        self.setFixedSize(self.d(self.FRAME[0]), self.d(self.FRAME[1]))
        self.setStyleSheet("QDialog { background: %s; }" % self.BODY_BG)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QtWidgets.QWidget(self)
        header.setFixedHeight(self.d(self.HEADER_H))
        header.setStyleSheet("background: %s;" % self.HEADER_BG)
        outer.addWidget(header)

        # ABSOLUTE placement in the header, because the design gives
        # absolute positions and a layout would only approximate them.
        # The body below is a layout, where the design gives a column.
        if icon and os.path.exists(icon):
            # LIVE VECTOR, not a pixmap. QSvgWidget re-renders the file
            # itself at whatever size and device resolution it is given,
            # so nothing is rasterised at a fixed size and handed on.
            #
            # His rule, 2026-08-02: "if i give you vector graphics it
            # should be vector graphics". The first attempt rasterised
            # at 60 and Qt upscaled it on a 2.0 display - it read as a
            # low-res bitmap, and rasterising at device resolution
            # would only have hidden that better. This has no raster
            # step to get wrong.
            glyph = QtSvgWidgets.QSvgWidget(icon, header)
            glyph.setStyleSheet("background: transparent;")
            glyph.setGeometry(self.d(33), self.d(36), self.d(60), self.d(60))

        for text, top, px, ink, bold in (
            (subtitle, 15, self.SUBTITLE_PX, self.LABEL_INK, False),
            (title, 47, self.TITLE_PX, self.TITLE_INK, True),
            (kind, 88, self.KIND_PX, self.LABEL_INK, False),
        ):
            if not text:
                continue
            label = QtWidgets.QLabel(str(text), header)
            font = QtGui.QFont(label.font())
            font.setPixelSize(self.d(px))
            font.setBold(bold)
            label.setFont(font)
            label.setStyleSheet("color: %s; background: transparent;" % ink)
            label.setGeometry(
                self.d(131), self.d(top),
                self.d(self.FRAME[0] - 131 - self.INSET),
                self.d(px + 8))

        body = QtWidgets.QWidget(self)
        outer.addWidget(body, 1)
        self.body_layout = QtWidgets.QVBoxLayout(body)
        inset = self.d(self.INSET)
        # 163 is the first field's top and the header ends at 132.
        self.body_layout.setContentsMargins(
            inset, self.d(163 - self.HEADER_H), inset, 0)
        # ZERO. add_field places the design's own gaps, which differ
        # above and below a label.
        self.body_layout.setSpacing(0)

    def add_field(self, widget, label: str = "") -> None:
        """A standard Houdini control, at the design's size and place.

        STANDARD means its LOOK is Houdini's - the grey boxes in his
        page are placeholders for real controls, not a paint job to
        reproduce. It does not mean the design stops applying: the
        geometry is still his, so the field fills the 442 column and
        stands 60 tall.

        The gaps are uneven and live here: 18 above a label, 9 between
        a label and its own field.
        """
        if label:
            if self.body_layout.count():
                self.body_layout.addSpacing(self.d(18))
            text = QtWidgets.QLabel(label, self)
            font = QtGui.QFont(text.font())
            font.setPixelSize(self.d(self.LABEL_PX))
            text.setFont(font)
            text.setStyleSheet(
                "color: %s; background: transparent;" % self.LABEL_INK)
            self.body_layout.addWidget(text)
            self.body_layout.addSpacing(self.d(9))
        widget.setFixedHeight(self.d(self.FIELD_H))
        self.body_layout.addWidget(widget)

    def add_buttons(self, reject_text: str, accept_text: str) -> None:
        """The design's two buttons: 202 x 42 each, filling the 442
        column with a 38 gap, at the design's y.

        Standard Houdini buttons - no stylesheet - but his geometry.
        Left at their natural size they huddled in the bottom-right
        corner, which is not what the page shows.
        """
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(self.d(self.BUTTON_GAP))
        for text, slot in ((reject_text, self.reject),
                           (accept_text, self.accept)):
            button = QtWidgets.QPushButton(text, self)
            button.setFixedSize(self.d(self.BUTTON[0]),
                                self.d(self.BUTTON[1]))
            button.clicked.connect(slot)
            row.addWidget(button)
        # 35 BELOW THE FIELD, from the page: the last field's bottom
        # edge is 334 and the buttons' top is 369. The same 35 as the
        # side padding - one value all round.
        #
        # Not a stretch. A stretch floated them to the bottom of the
        # body, which put a different gap above them at every dialog
        # height; his design places them, and the slack goes below.
        self.body_layout.addSpacing(self.d(35))
        self.body_layout.addLayout(row)
        self.body_layout.addStretch(1)


#: What a self-painted widget's disabled state looks like.
#:
#: Qt does not dim a pixmap a widget paints itself, so every widget
#: here that fully overrides paintEvent has to apply this by hand -
#: and until 2026-08-02 only ChipToggleButton did. The other two read
#: as live and simply broken: the Filter chip stayed fully lit beside
#: two chips that faded to 50%, and the size slider looked identical
#: in LIST mode while ignoring every click. overview.md §2 states both
#: behaviours ("Disabled chips paint at 50%", "the slider greys out").
DISABLED_OPACITY = 0.5


def apply_disabled_opacity(painter, widget) -> None:
    """Dim what follows when `widget` is disabled. One rule, so the
    three self-painted widgets cannot disagree about it again."""
    if not widget.isEnabled():
        painter.setOpacity(DISABLED_OPACITY)


class ClickSlider(QtWidgets.QSlider):
    """
    The slider provides continuous updates on slideing
    and allows for snapping to mouse on click. Paints its own groove and
    handle (Houdini 22 style) instead of relying on QSlider's
    sub-page/add-page stylesheet selectors - those rendered unpredictably
    across styles/platforms (colors landed on the correct side, but their
    declared heights did not), so this draws deterministically instead.

    Dragging is free/continuous everywhere except within SNAP_RADIUS
    units of one of SNAP_MARKS, where the value locks exactly onto that
    mark - a magnet zone around each reference point (not a snap grid
    across the whole range). Small tick marks on the track show where
    each of those reference points is.
    """

    # Colors per the "ui_wireframe 2 only menu" design file (2026-07-19).
    # LEFT_COLOR doubles as the project accent default; runtime overrides
    # it from prefs.accent_color via set_accent_color() regardless.
    LEFT_COLOR = QtGui.QColor("#5d7abd")
    LEFT_WIDTH = theme.ui_px(3)
    RIGHT_COLOR = QtGui.QColor(theme.color_hex("field"))  # was #434343 - byte-identical to this role, so
    #: the slider groove now follows the Houdini theme like the rest of the panel.
    RIGHT_WIDTH = theme.ui_px(3)
    HANDLE_COLOR = QtGui.QColor("#777f95")
    # Qt's pen for an ellipse is centered on its geometric edge, so the
    # border eats inward into the fill by roughly half its width rather
    # than sitting outside it - bumped the diameter up by 1 to compensate.
    HANDLE_DIAMETER = theme.ui_px(11)
    # Same grey as the toolbar-row background (panel.py), so the handle
    # border reads as punched out of the bar.
    HANDLE_BORDER_COLOR = QtGui.QColor(theme.color_hex("surface"))  # was #2d2d2d - byte-identical to this role, so
    #: the handle border now follows the Houdini theme like the rest of the panel.
    HANDLE_BORDER_WIDTH = theme.ui_px(1)
    # VALUE-domain constants (thumbnail sizes), deliberately unscaled.
    #: Grid opens here (2026-08-01, was 256). 128 is also the
    #: first SNAP_MARK, so the size the panel opens at is the
    #: size a drag falls back onto.
    DEFAULT_VALUE = 128
    SNAP_MARKS = (128, 256, 384)
    SNAP_RADIUS = 5
    TICK_COLOR = QtGui.QColor(theme.color_hex("text_dim"))  # was #696969 - byte-identical to this role, so
    #: the tick dots now follows the Houdini theme like the rest of the panel.
    # Pixel-art "circle" for the snap-mark tick, not a smooth ellipse -
    # exactly 5 pixels (center, up, down, left, right), not a thicker
    # diamond. Each "X" is one TICK_PIXEL_SIZE x TICK_PIXEL_SIZE square.
    TICK_PIXEL_SIZE = theme.ui_px(1)
    TICK_PATTERN = (
        ".X.",
        "XXX",
        ".X.",
    )

    def __init__(self) -> None:
        super(ClickSlider, self).__init__()
        # Instance-level so Preferences > Appearance > Accent Color can
        # override the class default per-panel without needing a subclass.
        self.left_color = QtGui.QColor(self.LEFT_COLOR)
        # Instance-level too: the snap marks (and their painted tick
        # dots) belong to the toolbar's thumbnail-size slider - other
        # uses (the Preferences parameter rows) set this to () for a
        # plain slider with no dots and no magnet zones.
        self.snap_marks = tuple(self.SNAP_MARKS)

    def set_accent_color(self, color: QtGui.QColor) -> None:
        """Overrides the filled (left) segment color and repaints."""
        self.left_color = QtGui.QColor(color)
        self.update()

    def _x_for_value(self, value: float) -> float:
        """X position for an arbitrary value using the same mapping as
        _handle_x() - shared so the default-value tick mark lines up
        exactly with where the handle would sit at that value. Inset by
        the handle radius on both ends so a circle centred here always
        stays fully inside the widget - without this, the centre reaches
        all the way to x=0/x=width at the value extremes and half of it
        gets clipped outside the widget bounds."""
        span = self.maximum() - self.minimum()
        fraction = 0.0 if span == 0 else (value - self.minimum()) / span
        radius = self.HANDLE_DIAMETER / 2
        usable = max(self.width() - 2 * radius, 0)
        return radius + fraction * usable

    def _handle_x(self) -> float:
        """X position of the handle centre for the current value."""
        return self._x_for_value(self.value())

    def _value_at_x(self, x: float) -> float:
        """Inverse of _x_for_value: maps a screen x back to a slider
        value, using the same radius inset. Without this, a click/drag at
        the left or right edge would set the value to the min/max, but
        the handle would then paint ~radius pixels away from where the
        click landed (since _x_for_value insets and this didn't)."""
        radius = self.HANDLE_DIAMETER / 2
        usable = max(self.width() - 2 * radius, 0)
        fraction = 0.0 if usable == 0 else (x - radius) / usable
        fraction = max(0.0, min(1.0, fraction))
        return self.minimum() + fraction * (self.maximum() - self.minimum())

    def _snap(self, value: float) -> int:
        """Locks onto the nearest SNAP_MARK if within SNAP_RADIUS of it,
        otherwise leaves the value as freely-dragged (just rounded to a
        whole number and clamped to the slider's own range)."""
        for mark in self.snap_marks:
            if abs(value - mark) <= self.SNAP_RADIUS:
                return mark
        return int(max(self.minimum(), min(self.maximum(), round(value))))

    def _draw_pixel_dot(self, painter: QtGui.QPainter, cx: float, cy: float) -> None:
        """Draws TICK_PATTERN centered at (cx, cy) as discrete filled
        squares - no antialiasing, so it reads as crisp pixel art rather
        than a smooth circle, matching the pixel-grid reference."""
        rows = self.TICK_PATTERN
        size = self.TICK_PIXEL_SIZE
        h = len(rows)
        w = len(rows[0])
        left = cx - (w * size) / 2.0
        top = cy - (h * size) / 2.0
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.TICK_COLOR)
        for row, line in enumerate(rows):
            for col, char in enumerate(line):
                if char == "X":
                    painter.drawRect(
                        QtCore.QRectF(left + col * size, top + row * size, size, size)
                    )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        # Because this fully overrides paintEvent, QSlider's own
        # disabled rendering never runs - so in LIST mode, where
        # _sync_slider_for_mode disables it and its docstring says "In
        # list it is greyed", it painted exactly as it does in GRID:
        # same accent fill, same handle, just parked at the minimum.
        # That reads as "the tiles are at their smallest", and since Qt
        # withholds mouse events from a disabled widget, as broken.
        apply_disabled_opacity(painter, self)

        mid_y = self.height() / 2
        handle_x = self._handle_x()

        left_pen = QtGui.QPen(self.left_color)
        left_pen.setWidth(self.LEFT_WIDTH)
        left_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        painter.setPen(left_pen)
        painter.drawLine(QtCore.QPointF(0, mid_y), QtCore.QPointF(handle_x, mid_y))

        right_pen = QtGui.QPen(self.RIGHT_COLOR)
        right_pen.setWidth(self.RIGHT_WIDTH)
        right_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        painter.setPen(right_pen)
        painter.drawLine(
            QtCore.QPointF(handle_x, mid_y), QtCore.QPointF(self.width(), mid_y)
        )

        # No antialiasing for the tick marks - crisp pixel-art squares,
        # not smoothed geometry, per the pixel-grid reference.
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        for mark in self.snap_marks:
            if self.minimum() <= mark <= self.maximum():
                tick_x = self._x_for_value(mark)
                self._draw_pixel_dot(painter, tick_x, mid_y)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        handle_pen = QtGui.QPen(self.HANDLE_BORDER_COLOR)
        handle_pen.setWidth(self.HANDLE_BORDER_WIDTH)
        painter.setPen(handle_pen)
        painter.setBrush(self.HANDLE_COLOR)
        radius = self.HANDLE_DIAMETER / 2
        painter.drawEllipse(QtCore.QPointF(handle_x, mid_y), radius, radius)

        painter.end()

    def _apply_mouse_value(self, x: float) -> None:
        """Shared body of click and drag handling: snap the value under
        the cursor and jump straight there (page/single step sized to
        the distance so the jump is one step, not an animation)."""
        value = self._snap(self._value_at_x(x))
        try:
            stepsize = int(abs(self.value() - value))
            self.setPageStep(stepsize)
            self.setSingleStep(stepsize)
        except Exception:
            pass
        self.setValue(value)

    @debug.guarded("ClickSlider.mousePressEvent")
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            e.accept()
            self._apply_mouse_value(e.pos().x())
        else:
            return super().mousePressEvent(e)

    @debug.guarded("ClickSlider.mouseMoveEvent")
    def mouseMoveEvent(self, ev: QtGui.QMouseEvent) -> None:
        ev.accept()
        self._apply_mouse_value(ev.pos().x())


class ThinProgressBar(QtWidgets.QWidget):
    """Minimal custom-painted progress bar. Deliberately not QProgressBar
    + a stylesheet: this project's Qt/macOS combination has repeatedly
    proven unreliable at honoring stylesheets on built-in widgets (see
    ClickSlider's history above), so this is hand-painted from the start
    instead of risking the same multi-iteration debugging cycle. Shares
    ClickSlider's fill color for a consistent look - no text, just a
    filled strip against a track."""

    FILL_COLOR = ClickSlider.LEFT_COLOR
    # Own constant, not ClickSlider.RIGHT_COLOR - that coupling meant
    # slider-only color tuning (a dedicated "dark side of the slider"
    # tweak) silently recolored this track too. Fixed value keeps the
    # look this always had before that coupling existed.
    TRACK_COLOR = QtGui.QColor("#1a1a1a")
    BAR_HEIGHT = theme.ui_px(4)

    def __init__(self) -> None:
        super().__init__()
        self._done = 0
        self._total = 0
        # Instance-level so Preferences > Appearance > Accent Color can
        # override the class default per-panel without needing a subclass.
        self.fill_color = QtGui.QColor(self.FILL_COLOR)
        self.setFixedHeight(self.BAR_HEIGHT)

    def set_accent_color(self, color: QtGui.QColor) -> None:
        """Overrides the fill color and repaints."""
        self.fill_color = QtGui.QColor(color)
        self.update()

    def set_progress(self, done: int, total: int) -> None:
        self._done = done
        self._total = total
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.TRACK_COLOR)
        if self._total > 0:
            fraction = min(max(self._done / self._total, 0.0), 1.0)
            fill_w = int(self.width() * fraction)
            if fill_w > 0:
                painter.fillRect(0, 0, fill_w, self.height(), self.fill_color)
        painter.end()


class GridHeaderView(QtWidgets.QHeaderView):
    """The Grid table's header: the sort arrow costs the column that
    HAS one, and not the other nine.

    `setSortIndicatorShown(True)` makes `QHeaderView` reserve room for
    the arrow in EVERY section, because any of them might become the
    sorted one. Measured 2026-08-04 at Houdini's 12pt: 21px each, so
    eight shown columns paid 147px for one arrow - and it lands
    hardest on the columns whose heading is all they contain. Favorite
    asked for 80px to hold a tick and the word "Favorite"; 59 without
    the reservation. Reported twice as sizing wrongly before this was
    measured rather than guessed at.

    `sectionSizeFromContents` is Qt's own hook for it. The amount taken
    back is what the base added, so the sections that are not sorted
    measure as they would with the indicator switched off - which is
    the identity `test_grid_columns` pins, rather than an arithmetic
    formula this has not read in Qt's source. `test_grid_columns` pins the
    identity rather than the formula - a non-sorted section measures
    the same as it would with the indicator switched off - so a change
    in Qt's arithmetic fails a test instead of drifting.
    """

    def sectionSizeFromContents(self, logicalIndex):
        size = super().sectionSizeFromContents(logicalIndex)
        if (not self.isSortIndicatorShown()
                or logicalIndex == self.sortIndicatorSection()):
            return size
        option = QtWidgets.QStyleOptionHeader()
        self.initStyleOption(option)
        margin = self.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_HeaderMargin, option, self)
        return QtCore.QSize(
            max(size.width() - size.height() - margin, 1), size.height())


class SectionTabBar(QtWidgets.QWidget):
    """Full-width section tab strip below the toolbar, per the
    "ui_wireframe 2 only menu" design file (2026-07-19 rev): a rounded-top
    tray at the left holding one text-label tab per section; the
    selected tab gets a rounded chip fill with a thin ring, unselected
    tabs are plain text. The tray's bottom edge is flush with the strip
    bottom and its color matches the category section's backdrop
    (#262626), so it reads as connected to the sidebar below - a
    folder-tab look. Replaces the SegmentedControl that used to sit
    inside cat_wrapper.

    Hand-painted for the same reason as its predecessor (and
    ClickSlider before that): stylesheet-driven buttons never reliably
    held their geometry on macOS native chrome.

    Design measurements (rendered px -> code px at the confirmed 2x
    display scale; heights/sizes/paddings ARE exact, button placement
    is not): tray height 46 -> 23, tray top corner radius
    8 -> 4, chip height 34 -> 17, chip corner radius 8 -> 4, ring
    2 -> 1, text side padding inside a chip 15 -> 7.5, gap between
    chips 5 -> 2.5, tray-edge-to-first-chip inset 6 -> 3, tray left
    offset 6 -> 3. Half-pixel code values are painted via QRectF - on
    the 2x display they land on physical pixel boundaries. Full strip
    height is 28 (56 rendered vs the design's 55 - 55 isn't reachable
    with integer widget heights; the spare pixel goes above the tray).
    """

    #: emits the key of the tab that just became checked (only on an
    #: actual change, matching QAbstractButton.setChecked()'s own
    #: emit-only-on-change behavior)
    segmentClicked = QtCore.Signal(str)

    HEIGHT = theme.ui_px(28)
    TRAY_HEIGHT = theme.ui_px(23)
    TRAY_RADIUS = theme.ui_px(4)
    TRAY_LEFT = theme.ui_px(3)
    CHIP_HEIGHT = theme.ui_px(17)
    CHIP_RADIUS = theme.ui_px(4)
    CHIP_PAD_X = theme.ui_px(7.5)
    CHIP_GAP = theme.ui_px(2.5)
    CHIP_INSET = theme.ui_px(3)

    # Theme-derived (helpers/theme.py): identical to the old literal
    # constants under Houdini's default theme, follows any other theme
    # automatically. The chip pair is an ACCENT shade (Houdini's own
    # example panel drives its checked/tab states from accent variants).
    STRIP_COLOR = theme.color("surface")  # matches the toolbar row
    TRAY_COLOR = theme.color("surface_low")  # matches cat backdrop
    CHIP_FILL = theme.color("tab_chip")
    CHIP_RING = theme.color("tab_ring")
    TEXT_SELECTED = theme.color("text_bright")
    TEXT_UNSELECTED = theme.color("text")
    # Not in the design (no tab hover state drawn there) - a modest
    # text-whitening on hover, matching the toolbar icons' hover color.
    TEXT_HOVER = QtGui.QColor("#cccdcd")

    def __init__(self, segments: list) -> None:
        """segments: list of (key, label) pairs, left to right."""
        super().__init__()
        self._segments = list(segments)
        self._checked_key = None
        self._hover_key = None
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def setChecked(self, key: str, emit: bool = True) -> None:
        """Selects the given tab. Emits segmentClicked only if this
        actually changes the current selection.

        emit=False lets a caller set the initial visual "checked" state
        at construction time without firing the signal - needed because
        panel.py builds this widget inside init_ui(), before setup() has
        created the models _on_tab_toggled's handlers depend on."""
        if key != self._checked_key:
            self._checked_key = key
            self.update()
            if emit:
                self.segmentClicked.emit(key)

    def _chip_rects(self) -> list:
        """[((key, label), QRectF), ...] - the chip-sized rect for every
        tab (also the hit target for unselected tabs, which paint text
        only). Measured against the CURRENT font, so the panel's font
        stamp is always respected regardless of construction order."""
        metrics = self.fontMetrics()
        tray_top = self.height() - self.TRAY_HEIGHT
        chip_y = tray_top + (self.TRAY_HEIGHT - self.CHIP_HEIGHT) / 2.0
        x = self.TRAY_LEFT + self.CHIP_INSET
        rects = []
        for key, label in self._segments:
            w = metrics.horizontalAdvance(label) + 2 * self.CHIP_PAD_X
            rects.append(
                ((key, label), QtCore.QRectF(x, chip_y, w, self.CHIP_HEIGHT))
            )
            x += w + self.CHIP_GAP
        return rects

    def _key_at(self, pos) -> str | None:
        for (key, _), rect in self._chip_rects():
            if rect.contains(QtCore.QPointF(pos)):
                return key
        return None

    def sizeHint(self) -> QtCore.QSize:
        rects = self._chip_rects()
        right = rects[-1][1].right() + self.CHIP_INSET if rects else 0
        return QtCore.QSize(int(right) + self.TRAY_LEFT, self.HEIGHT)

    @debug.guarded("SectionTabBar.mousePressEvent")
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        key = self._key_at(event.pos())
        if key is not None:
            self.setChecked(key)

    @debug.guarded("SectionTabBar.mouseMoveEvent")
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        key = self._key_at(event.pos())
        if key != self._hover_key:
            self._hover_key = key
            # Pointing hand only over an actual tab - this strip spans
            # the whole panel width, most of it empty.
            if key is not None:
                self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
            self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        if self._hover_key is not None:
            self._hover_key = None
            self.unsetCursor()
            self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self.STRIP_COLOR)

        rects = self._chip_rects()
        if rects:
            # Tray: rounded top corners only - the rect is extended one
            # radius past the widget bottom, so the bottom rounding is
            # clipped off and the tray sits flush against whatever is
            # below (visually connecting to the category sidebar).
            tray_top = self.height() - self.TRAY_HEIGHT
            tray_right = rects[-1][1].right() + self.CHIP_INSET
            tray_path = QtGui.QPainterPath()
            tray_path.addRoundedRect(
                QtCore.QRectF(
                    self.TRAY_LEFT,
                    tray_top,
                    tray_right - self.TRAY_LEFT,
                    self.TRAY_HEIGHT + self.TRAY_RADIUS,
                ),
                self.TRAY_RADIUS,
                self.TRAY_RADIUS,
            )
            painter.fillPath(tray_path, self.TRAY_COLOR)

        for (key, label), rect in rects:
            checked = key == self._checked_key
            if checked:
                chip_path = QtGui.QPainterPath()
                chip_path.addRoundedRect(rect, self.CHIP_RADIUS, self.CHIP_RADIUS)
                painter.fillPath(chip_path, self.CHIP_FILL)
                ring_w = theme.ui_px(1.0)
                half = ring_w / 2.0
                pen = QtGui.QPen(self.CHIP_RING)
                pen.setWidthF(ring_w)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    rect.adjusted(half, half, -half, -half),
                    self.CHIP_RADIUS,
                    self.CHIP_RADIUS,
                )
            if checked:
                painter.setPen(self.TEXT_SELECTED)
            elif key == self._hover_key:
                painter.setPen(self.TEXT_HOVER)
            else:
                painter.setPen(self.TEXT_UNSELECTED)
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, label)

        painter.end()


def draw_chip(painter, rect, fill, ring, inner_border=None):
    """Draws the design's rounded button chip: fill + a light ring on
    the outer edge, optionally a darker ring just inside it (the
    clicked state has the inner ring, the hover state doesn't). Shared
    by IconMenuButton and ChipToggleButton so the two hover looks can't
    drift apart. Rects sit on half-pen-width centers so the ring pens
    draw crisp. All geometry runs through the UI scale so the chips
    match Houdini's own control sizes on scaled (Linux) displays."""
    ring_w = theme.ui_px(1)
    half = ring_w / 2.0
    outer = QtCore.QRectF(rect).adjusted(half, half, -half, -half)
    painter.setPen(QtGui.QPen(ring, ring_w))
    painter.setBrush(fill)
    painter.drawRoundedRect(outer, theme.ui_px(5), theme.ui_px(5))
    if inner_border is not None:
        inset = ring_w + half
        inner = QtCore.QRectF(rect).adjusted(inset, inset, -inset, -inset)
        painter.setPen(QtGui.QPen(inner_border, ring_w))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(inner, theme.ui_px(4), theme.ui_px(4))


class ToggleSwitch(QtWidgets.QCheckBox):
    """Pill toggle switch - a drop-in QCheckBox replacement (same
    signals and checked API, same row layout: control with its text on
    the right). Hand-painted like every styled widget in this project.

    Colors come from the theme engine roles the design's swatches map
    to: ON = the accent-family chip fill (section-tab blue) with the
    accent-colored knob, OFF = the field grey with a dim grey knob;
    both tracks carry a 1px darker border ring. Sizes are DESIGN px,
    scaled here."""

    # 46x30 rendered px (2x rule: code halves) - the design's "slightly
    # fatter" revision over the first 52x26 pass.
    TRACK_W = 23
    TRACK_H = 15
    KNOB_INSET = 2
    GAP = 8

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QtCore.QSize:
        fm = QtGui.QFontMetrics(self.font())
        w = (
            theme.ui_px(self.TRACK_W)
            + (theme.ui_px(self.GAP) + fm.horizontalAdvance(self.text())
               if self.text() else 0)
            + theme.ui_px(2)
        )
        h = max(theme.ui_px(self.TRACK_H) + theme.ui_px(4),
                fm.height() + theme.ui_px(2))
        return QtCore.QSize(w, h)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def hitButton(self, pos: QtCore.QPoint) -> bool:
        # The whole row (track + text) toggles, like a checkbox's text.
        return self.rect().contains(pos)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        tw = theme.ui_px(self.TRACK_W)
        th = theme.ui_px(self.TRACK_H)
        y = (self.height() - th) / 2.0
        # Half-pen-width inset so the scaled border pen renders crisp.
        ring_w = theme.ui_px(1.0)
        half = ring_w / 2.0
        track = QtCore.QRectF(half, y + half, tw - ring_w, th - ring_w)
        radius = track.height() / 2.0
        if self.isChecked():
            # Houdini's own toggle switches use the theme HIGHLIGHT
            # (yellow) for the on state - knob at full strength, track
            # a deep-dimmed version of the same color.
            knob = theme.color("star")
            fill = QtGui.QColor(knob).darker(260)
        else:
            fill = theme.color("field")
            knob = theme.color("text_dim")
        p.setPen(QtGui.QPen(fill.darker(140), ring_w))
        p.setBrush(fill)
        p.drawRoundedRect(track, radius, radius)
        inset = theme.ui_px(self.KNOB_INSET)
        d = th - 2 * inset
        kx = (tw - inset - d) if self.isChecked() else inset
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QtCore.QRectF(kx, y + inset, d, d))
        if self.text():
            p.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
            p.drawText(
                QtCore.QRectF(
                    tw + theme.ui_px(self.GAP), 0,
                    self.width() - tw - theme.ui_px(self.GAP), self.height(),
                ),
                QtCore.Qt.AlignmentFlag.AlignVCenter
                | QtCore.Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )


class IconMenuButton(QtWidgets.QWidget):
    """Icon button that pops a QMenu (Library/View/Renderer at the
    toolbar's right end, per the "ui_wireframe 2 only menu" design
    file).

    Fully hand-painted. The first version was a plain QToolButton meant
    to inherit Houdini's own button chrome for the pressed/open look -
    live testing showed that chrome provides NO visible open state at
    all in this panel, plus a stray line artifact under each button
    (menu-indicator/chrome residue), so this went the same way every
    styled widget in this project eventually has: own every pixel
    (ClickSlider, SegmentedControl, and the old text MenuBarButton all
    hit the same wall). Hover/open state is tracked explicitly and
    cleared via the menu's aboutToHide signal - the proven MenuBarButton
    pattern that avoids the stuck-highlight-after-popup Qt quirk.

    States, per the design's "Hover" and "Clicked" groups: idle = icon
    in #5d7abd, no chip; hover = grey chip (#424142 fill, #555455 outer
    ring, no inner ring) behind the whitened icon; open = blue chip
    (#2d4075 fill, #1e2c50 inner border, #707ca3 outer ring) behind the
    whitened icon. In both chip states the icon's punch-out details
    switch to the chip's own fill color so they keep reading as holes."""

    IDLE_BODY = "#5d7abd"
    LIT_BODY = "#cccdcd"
    IDLE_TRIANGLE = "#7f807f"
    LIT_TRIANGLE = "#a5b3d4"
    PUNCH_OUT = "#2d2d2d"
    OPEN_PUNCH_OUT = "#2d4075"
    HOVER_PUNCH_OUT = "#424142"
    CHIP_FILL = QtGui.QColor("#2d4075")
    CHIP_BORDER = QtGui.QColor("#1e2c50")
    CHIP_RING = QtGui.QColor("#707ca3")
    HOVER_CHIP_FILL = QtGui.QColor("#424142")
    HOVER_CHIP_RING = QtGui.QColor("#555455")
    TEXT_COLOR = QtGui.QColor("#e6e6e6")
    # Icons are rendered at 4x the icon size so painting scales a sharp
    # pixmap down on the retina display instead of a soft one up.
    RENDER_SCALE = 4

    def __init__(
        self,
        menu: QtWidgets.QMenu | None,
        svg_path: str,
        # 18 with the 36-unit body-centered viewBoxes keeps the icon
        # body at the same ~29px rendered size as the design. Sizes are
        # in DESIGN px; the UI scale is applied here so every call site
        # stays scale-agnostic.
        icon_size: int = 18,
        button_size: int = 24,
        # With menu=None the button is a plain ACTION button: a click
        # calls on_click instead of popping a menu (the gear goes
        # straight into Preferences; its icon carries no menu triangle).
        on_click=None,
        fallback_label: str = "",
    ) -> None:
        super().__init__()
        self._menu = menu
        self._on_click = on_click
        self._hovered = False
        self._open = False
        self._icon_size = theme.ui_px(icon_size)
        button_size = theme.ui_px(button_size)
        self.setFixedSize(button_size, button_size)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        render_size = self._icon_size * self.RENDER_SCALE
        self._idle_pm = render_svg_pixmap(svg_path, render_size)
        self._hover_pm = render_svg_pixmap(
            svg_path,
            render_size,
            {
                self.IDLE_BODY: self.LIT_BODY,
                self.IDLE_TRIANGLE: self.LIT_TRIANGLE,
                self.PUNCH_OUT: self.HOVER_PUNCH_OUT,
            },
        )
        self._open_pm = render_svg_pixmap(
            svg_path,
            render_size,
            {
                self.IDLE_BODY: self.LIT_BODY,
                self.IDLE_TRIANGLE: self.LIT_TRIANGLE,
                self.PUNCH_OUT: self.OPEN_PUNCH_OUT,
            },
        )
        # Graceful fallback if the asset is missing: draw the menu title
        # (or the given label) as text so the button stays usable.
        self._fallback_text = (
            "" if (svg_path and os.path.exists(svg_path))
            else (menu.title() if menu is not None else fallback_label)
        )
        if menu is not None:
            menu.aboutToHide.connect(self._on_menu_closed)

    def _on_menu_closed(self) -> None:
        self._open = False
        # The mouse may or may not still be over this button once the
        # menu closes, and Qt does not reliably resend hover/leave
        # events across a popup closing - check the cursor directly.
        self._hovered = self.rect().contains(
            self.mapFromGlobal(QtGui.QCursor.pos())
        )
        self.update()

    @debug.guarded("IconMenuButton.mousePressEvent")
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        if self._menu is None:
            if self._on_click is not None:
                self._on_click()
            return
        self._open = True
        self.update()
        self._menu.popup(self.mapToGlobal(QtCore.QPoint(0, self.height())))

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, True
        )
        # The other hand-painted toolbar button. It is a bare QWidget,
        # so Qt gives it no disabled treatment either - and the panel
        # disables the Filter chip in the online world alongside the
        # favourites star and Comments, whose own comment says "Same
        # treatment, so the three read as one row". What rendered was
        # two dim and one bright-but-dead.
        apply_disabled_opacity(painter, self)
        if self._open:
            # The design's clicked chip: blue fill, light outer ring,
            # darker border ring just inside it.
            draw_chip(
                painter, self.rect(), self.CHIP_FILL, self.CHIP_RING,
                self.CHIP_BORDER,
            )
        elif self._hovered:
            # The design's hover chip: the grey sibling - fill + light
            # outer ring only, no inner border ring.
            draw_chip(
                painter, self.rect(), self.HOVER_CHIP_FILL,
                self.HOVER_CHIP_RING,
            )
        if self._fallback_text:
            painter.setPen(self.TEXT_COLOR)
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self._fallback_text,
            )
        else:
            if self._open:
                pm = self._open_pm
            elif self._hovered:
                pm = self._hover_pm
            else:
                pm = self._idle_pm
            offset = (self.width() - self._icon_size) // 2
            target = QtCore.QRect(
                offset, offset, self._icon_size, self._icon_size
            )
            painter.drawPixmap(target, pm)
        painter.end()


class ChipToggleButton(QtWidgets.QToolButton):
    """Checkable icon button (favorites star, grid/list toggle) with the
    exact same hand-painted grey hover chip as IconMenuButton - the
    hover state is meant to match across favorites/grid-list/menu
    buttons, with icons whitening to the same light color.

    Half-opacity when disabled (DISABLED_OPACITY), because a
    self-painted button gets no dimming from Qt.

    Subclasses QToolButton so all existing wiring keeps working
    untouched (toggled signal, setChecked/isChecked, signal blocking),
    but paints entirely itself: QAbstractButton still handles the
    click-to-toggle mechanics, which don't depend on paint. No popup
    menu is involved, so plain enter/leave hover tracking is safe here -
    the stuck-hover Qt quirk only bites across a popup closing."""

    RENDER_SCALE = 4

    def __init__(self, button_size: int = 24, icon_size: int = 16) -> None:
        super().__init__()
        self.setCheckable(True)
        # Sizes are in DESIGN px; the UI scale is applied here so call
        # sites stay scale-agnostic (matches IconMenuButton).
        button_size = theme.ui_px(button_size)
        self.setFixedSize(button_size, button_size)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._icon_size = theme.ui_px(icon_size)
        self._hovered = False
        self._pms = {}

    #: What "disabled" looks like on a chip that paints itself.
    #: Kept as a class attribute because a test pins it here, but
    #: it is the module-level rule every self-painted widget now
    #: shares - one value, not three.
    DISABLED_OPACITY = DISABLED_OPACITY

    def set_art(self, off_path, on_path=None, lighten_on_hover=True,
                recolour=None, recolour_on=None):
        """THE one way a chip gets its four states.

        Every chip was building these by hand - render the off art,
        render the on art, render the off art again through the lit
        map - and each copy drifted a little: two of them ended up
        with a state the others did not have. A chip differs from
        another chip in its ART, not in its logic, so the logic lives
        here and the art is what a caller passes.

        The house rule the existing chips already followed, now
        written down: AT REST, BOTH STATES ARE THE ART AS DRAWN. The
        picture says on or off - a filled star, a list instead of a
        grid - and nothing is re-tinted to say it again. Hover
        lightens.

        `lighten_on_hover=False` for a chip whose on-state is carried
        by COLOUR rather than by shape: lightening it there erases the
        very thing that says it is on. The favourites star has always
        done this for its checked+hovered state; Comments and
        Categories do it for all four.

        `on_path=None` means one drawing for both states.

        `recolour` is for art that serves TWO places at once: the
        Comments glyph is the section's blue where it belongs to the
        section, and the toolbar's own blue on the toolbar. Passing
        the map here keeps that in one place instead of a second copy
        of the drawing.
        """
        size = self._icon_size * self.RENDER_SCALE
        base = dict(recolour or {})
        # The ON state may recolour differently - that is how a chip
        # says "you are in this state" with a colour instead of a
        # second drawing. The favourites star does it with two files;
        # one file and a tint is the same idea with less to keep in
        # step.
        on_map = dict(recolour_on) if recolour_on else base
        lit = dict(base)
        lit[IconMenuButton.IDLE_BODY] = IconMenuButton.LIT_BODY

        def art(path, tints):
            return render_svg_pixmap(path, size, tints) if tints \
                else render_svg_pixmap(path, size)

        off = art(off_path, base)
        on = art(on_path or off_path, on_map)
        self.set_state_pixmaps(
            off,
            on,
            art(off_path, lit) if lighten_on_hover else off,
            (art(on_path or off_path, lit) if lighten_on_hover else on),
        )

    def set_state_pixmaps(self, off_pm, on_pm, hover_off_pm, hover_on_pm):
        """Pixmaps keyed by (checked, hovered)."""
        self._pms = {
            (False, False): off_pm,
            (True, False): on_pm,
            (False, True): hover_off_pm,
            (True, True): hover_on_pm,
        }
        self.update()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, True
        )
        if self._hovered and self.isEnabled():
            draw_chip(
                painter, self.rect(), IconMenuButton.HOVER_CHIP_FILL,
                IconMenuButton.HOVER_CHIP_RING,
            )
        # A DISABLED chip is half there. Qt does not dim a pixmap a
        # widget paints itself, so a control that had been switched off
        # looked exactly like one that was live - the favourites star,
        # disabled while the online browser is showing because online
        # records have no favourite state, read as simply not working.
        apply_disabled_opacity(painter, self)
        pm = self._pms.get((self.isChecked(), self._hovered))
        if pm is not None:
            offset = (self.width() - self._icon_size) // 2
            painter.drawPixmap(
                QtCore.QRect(offset, offset, self._icon_size, self._icon_size),
                pm,
            )
        painter.end()




class SideIconPinner(QtCore.QObject):
    """Keeps an icon QLabel pinned to one edge of a line edit (left or
    right), inset by a fixed margin, vertically centered. Needed because
    the line edit isn't fixed-width (only max-width) - a one-time move()
    wouldn't stay correct across a panel resize, so this reacts to the
    line edit's own Resize events instead. Used for line_filter's filter
    icon."""

    def __init__(
        self,
        line_edit: QtWidgets.QLineEdit,
        icon_label: QtWidgets.QLabel,
        margin: int,
        side: str = "right",
    ) -> None:
        super().__init__(line_edit)
        self._line_edit = line_edit
        self._icon_label = icon_label
        self._margin = margin
        self._side = side
        line_edit.installEventFilter(self)
        self.reposition()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj is self._line_edit and event.type() == QtCore.QEvent.Type.Resize:
            self.reposition()
        return False

    def reposition(self) -> None:
        w = self._icon_label.width()
        h = self._icon_label.height()
        if self._side == "left":
            x = self._margin
        else:
            x = self._line_edit.width() - self._margin - w
        y = (self._line_edit.height() - h) // 2
        self._icon_label.move(max(x, 0), max(y, 0))

def pick_color(initial, parent=None, title="Select Color"):
    """One colour picker for the whole app: Houdini's own when it can
    be shown, Qt's when it cannot. Returns a QtGui.QColor or None.

    Houdini's picker (hou.ui.selectColor) is the one users know, with
    its palettes and eyedropper - but it is a NATIVE modal, and a
    native dialog raised while a Qt modal exec loop is active lands
    UNDER it, invisible (recorded; the nested modal loops crashed
    Houdini once). activeModalWidget() answers that at call time, so
    callers need no per-site knowledge: the icon dialog (exec_() modal)
    gets Qt's picker, menu handlers and the non-modal prefs dialog get
    Houdini's. Headless hython has no hou.ui and takes the Qt path too.

    Mapping is the straight 0-1 <-> 0-255 SideFX's own
    ColorSwatchButton uses.
    """
    from PySide6 import QtGui, QtWidgets

    if isinstance(initial, str):
        initial = QtGui.QColor(initial) if initial else QtGui.QColor()

    use_native = False
    try:
        import hou
        use_native = (hasattr(hou, "ui")
                      and QtWidgets.QApplication.activeModalWidget()
                      is None)
    except ImportError:
        pass

    if use_native:
        import hou
        seed = None
        if initial is not None and initial.isValid():
            seed = hou.Color((initial.redF(), initial.greenF(),
                              initial.blueF()))
        try:
            chosen = hou.ui.selectColor(initial_color=seed)
        except hou.Error as exc:
            from amaze.core import debug
            debug.event("ui", "houdini colour picker failed - falling "
                        "back to Qt", error=str(exc))
            chosen = None
            use_native = False
        else:
            if chosen is None:
                return None                       # cancelled
            r, g, b = chosen.rgb()
            return QtGui.QColor.fromRgbF(
                max(0.0, min(1.0, r)), max(0.0, min(1.0, g)),
                max(0.0, min(1.0, b)))

    picked = QtWidgets.QColorDialog.getColor(
        initial if initial is not None and initial.isValid()
        else QtGui.QColor("#4af2a1"),
        parent, title)
    return picked if picked.isValid() else None


class HeldPane(QtWidgets.QWidget):
    """A splitter side pane that OWNS its width.

    The construction's law is one flexible pane - the grid - so a
    stretch-0 pane gets exactly what its sizeHint asks for, at launch
    AND every time it is shown. Each side pane must therefore ask for
    something: the remembered dragged width when there is one, the
    design width otherwise.

    BOTH side panes are this. The sidebar was built on it; the Comments
    pane carried a copy of the sizeHint plus fifty lines of splitter
    arithmetic on the panel, which measured identical to doing nothing
    (the splitter had already honoured the hint by the time it ran).
    Lives here rather than in panel.py so the pane modules can share it
    without importing the panel that holds them.
    """

    def __init__(self, preferences, pref_key, default_px, parent=None):
        super().__init__(parent)
        self._preferences = preferences
        self._pref_key = pref_key
        self._default_px = default_px

    def sizeHint(self):
        hint = super().sizeHint()
        remembered = int(getattr(
            self._preferences, self._pref_key, 0) or 0)
        return QtCore.QSize(remembered or self._default_px,
                            hint.height())
