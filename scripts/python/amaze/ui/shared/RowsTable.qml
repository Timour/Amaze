// Every table: Qt's TableView under Houdini's header, in its ScrollView; whole rows highlighted.
import QtQuick
import houdini.pluto
import houdini.ui

Item {
    id: root

    property alias model: view.model    // set before `selectionModel`: Qt points a selection at its rows
    property alias selectionModel: view.selectionModel
    property var columns: []    // per model column: its width, 0 to hide it, if a tick, an inset, if whole
    property real rowHeight: 0    // a row's height as drawn; 0 for the ground's own
    property bool scrolls: true    // false: the rows take the height they need and a page scrolls them
    readonly property real contentHeight: header.height + view.contentHeight
    property var drawn: ({})    // `amazetheme.drawn_list`: the header's height, the text inset, the tick
    property int sortColumn: -1    // the heading drawn sorted; -1 for none
    property bool descending: false
    property var ink: colour => colour    // a cell's own text colour as it is drawn
    property bool headings: true    // the heading row over the columns
    property bool ownKeys: false    // the arrow and page keys taken here, where no pane hands on hotkeys
    readonly property bool hotkeysFirst: true    // Amaze's hotkeys before its ScrollView's own arrow scrolling
    signal rowClicked(int row, int modifiers)    // the user's click; row -1 is the space below the rows
    signal rowDoubleClicked(int row)
    signal rowKeyed(int row, int modifiers)    // the user's move by an Amaze hotkey landed on `row`
    signal headingClicked(int column)
    signal rowDragged(int row, int modifiers)    // a press on row `row` moved past the drag distance

    function rowAt(x, y) {    // the row at (x, y) in the list, -1 for the space below the rows
        const at = root.mapToItem(view.contentItem, x, y)
        return view.cellAtPosition(at.x, at.y).y
    }
    function step(name, extend) {    // an Amaze hotkey's move, a row at a time or a page of rows
        keys.step(name, extend, view.rows,
                  Math.max(1, Math.floor(view.height * view.rows / Math.max(view.contentHeight, 1))), view.moved)
    }

    Keys.forwardTo: root.ownKeys ? [view] : []    // the table given the keys: the rows take them

    readonly property int last: {    // the last shown column, which takes the rest of the width
        let found = -1
        for (let column = 0; column < root.columns.length; column++)
            if (root.columns[column].width)
                found = column
        return found
    }

    function widthOf(column) {    // the user's dragged width, else L01's; the last one fills the row
        const drawn = column < root.columns.length ? root.columns[column].width : 0
        if (!drawn)
            return 0
        const set = view.explicitColumnWidth(column)
        if (set >= 0)
            return set
        if (column !== root.last)
            return drawn
        let used = 0
        for (let before = 0; before < column; before++)
            used += root.widthOf(before)
        return Math.max(drawn, view.width - used)
    }

    HorizontalHeaderView {
        id: header
        width: root.width
        height: root.headings ? root.drawn.header_h : 0
        visible: root.headings
        syncView: view
        clip: true
        delegate: HeadingCellDelegate {
            required property string display
            required property int column
            implicitHeight: root.drawn.header_h
            cellPadding: root.drawn.text_inset / 2    // Houdini's heading pads its text twice this
            text: display
            isSortColumn: column === root.sortColumn
            reversed: root.descending
            onTapped: root.headingClicked(column)
        }
    }

    ScrollArea {
        anchors.fill: parent
        anchors.topMargin: header.height

        TableView {
            id: view

            clip: true
            interactive: false    // no drag scrolling, as Houdini's Context Options list
            pointerNavigationEnabled: false    // Qt's own click only makes a row current: `rowClicked` selects
            keyNavigationEnabled: false    // keys are Amaze's hotkeys, landing through `step`
            Keys.enabled: root.ownKeys    // before the ScrollView round it, which scrolls on arrows
            Keys.onUpPressed: event => root.step("up", event.modifiers & Qt.ShiftModifier)
            Keys.onDownPressed: event => root.step("down", event.modifiers & Qt.ShiftModifier)
            Keys.onPressed: event => {    // the page keys, by the names Houdini's hotkeys give them
                const name = {[Qt.Key_Home]: "home", [Qt.Key_End]: "end",
                              [Qt.Key_PageUp]: "page_up", [Qt.Key_PageDown]: "page_down"}[event.key]
                if (name !== undefined) {
                    root.step(name, event.modifiers & Qt.ShiftModifier)
                    event.accepted = true
                }
            }
            columnWidthProvider: column => root.widthOf(column)
            rowHeightProvider: row => root.rowHeight > 0 ? root.rowHeight : -1    // -1: the ground's
            onWidthChanged: forceLayout()

            function moved(name, from) {    // one row up or down, -1 for a move a list does not take
                return name === "up" ? Math.max(0, from - 1)
                     : name === "down" ? Math.min(view.rows - 1, from + 1) : -1
            }

            RowKeys {
                id: keys
                selectionModel: root.selectionModel
                onChose: (row, modifiers) => {
                    root.rowKeyed(row, modifiers)
                    view.positionViewAtRow(row, TableView.Contain)
                }
            }

            WheelScroll {    // Qt's own wheel is off with its drag scrolling
                enabled: root.scrolls
                view: view
            }
            RowStripes {
                view: view
                rowHeight: root.rowHeight
            }
            Item {    // under the rows and the space below them, so one handler takes every click
                parent: view.contentItem
                z: -2
                width: Math.max(view.width, view.contentWidth)
                height: Math.max(view.height, view.contentHeight)
                TapHandler {    // a tap handler gives no focus (Qt gives it only to an item taking the press)
                    id: tap
                    onTapped: {
                        view.forceActiveFocus(Qt.MouseFocusReason)
                        root.rowClicked(view.cellAtPosition(point.position).y, point.modifiers)
                    }
                    onDoubleTapped: root.rowDoubleClicked(view.cellAtPosition(point.position).y)
                }
                DragOut {
                    id: drag
                    onStarted: (at, modifiers) => root.rowDragged(view.cellAtPosition(at).y, modifiers)
                }
            }

            delegate: RowGround {
                id: cell

                required property var model
                required property int row
                required property int column
                required property bool selected
                readonly property bool tick: column < root.columns.length && root.columns[column].tick
                readonly property var inset: column < root.columns.length ? root.columns[column].inset : undefined
                readonly property bool whole: column < root.columns.length && !!root.columns[column].whole

                highlighted: selected
                alternate: view.alternatingRows && row % 2 === 1
                clip: true

                Text {
                    visible: !cell.tick
                    x: cell.inset !== undefined ? cell.inset : root.drawn.text_inset
                    width: parent.width - x
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    elide: cell.whole ? Text.ElideMiddle : Text.ElideRight    // a long path keeps both its ends
                    color: cell.highlighted || !cell.model.foreground ? cell.fg : root.ink(cell.model.foreground)
                    text: cell.model.display ?? ""
                    ToolTip.text: text    // a cut value whole, as Houdini's theme list tips a cut name
                    ToolTip.visible: SharedState.tipsShown && truncated && over.hovered
                    ToolTip.delay: Config.toolTipDelay

                    HoverHandler {
                        id: over
                        enabled: cell.whole
                    }
                }
                AmazeIcon {    // a yes is L01's tick at its box; a no shows nothing
                    visible: cell.tick && !!cell.model.display
                    x: root.drawn.tick_pad
                    anchors.verticalCenter: parent.verticalCenter
                    width: root.drawn.tick_side
                    height: width
                    file: "list_tick.svg"
                }
            }
        }
    }
}
