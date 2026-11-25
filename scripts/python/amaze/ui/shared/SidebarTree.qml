// The sidebar: Houdini's TreeView and TreeViewDelegate over the engine's rows, for every section.
import QtQuick
import QtQuick.Controls.impl
import houdini.pluto
import houdini.ui

TreeView {
    id: root

    property bool counts: true    // each row's count after its name; All always shows its total
    property var drawn: ({})    // `amazetheme.drawn_sidebar`: the colour bar's place, off G01
    property bool wheelFix: false    // the wheel as Houdini's Context Options list takes it; off, Qt's
    property int dropRow: -1    // the row a dragged tile would drop on, lit as the selected rows are
    property int gapRow: -1    // the row a dragged row would go above, lined; the row count for the end
    property Item holder: null    // the row under a press: no flick takes it, so it can be dragged
    signal stepped()    // a key that Qt's own navigation moves the current row by; no other key
    signal rowDragged(var index)    // a press on the row at `index` moved past the drag distance
    readonly property var steps: [Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                                  Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End]

    clip: true
    interactive: holder === null    // as the grid holds its flicking for a tile's drag
    selectionBehavior: TableView.SelectRows    // Qt's view alone takes a click: the pane follows its current row
    editTriggers: TableView.NoEditTriggers    // rename comes with the menus
    columnWidthProvider: column => column === 0 ? width : 0    // the name's column; the colour cell's is hidden
    onWidthChanged: forceLayout()
    Keys.onPressed: event => {    // not accepted, so Qt's own navigation still moves the row
        if (root.steps.includes(event.key))
            root.stepped()
    }

    RowStripes {
        view: root
    }
    WheelScroll {
        view: root
        enabled: root.wheelFix
    }

    function indexAt(x, y) {    // the row at (x, y) in the tree, an invalid index below the rows
        const at = root.mapToItem(root.contentItem, x, y)
        return root.index(root.cellAtPosition(at.x, at.y).y, 0)
    }
    function gapAt(x, y) {    // [the row a row dropped at (x, y) goes above, that row's index]; null off it
        if (x < 0 || y < 0 || x > width || y > height)
            return null
        const at = root.mapToItem(root.contentItem, x, y)
        const row = root.cellAtPosition(at.x, at.y).y
        const cell = row < 0 ? null : root.itemAtCell(Qt.point(0, row))
        const above = row < 0 ? root.rows : (cell && at.y > cell.y + cell.height / 2 ? row + 1 : row)
        return [above, root.index(above, 0)]    // past the last row the index is invalid: the end
    }
    function open(index) {    // the folder at `index` and every folder above it
        expandToIndex(index)
        expand(rowAtIndex(index))
    }

    // Houdini's row with Amaze's colour bar first, the count after the name, a warning on a lost folder
    delegate: TreeViewDelegate {
        id: entry    // never `row`: Qt reads the row number by that name in the delegate's context

        readonly property bool lost: entry.model.unreachable === true    // its folder could not be opened
        readonly property var count: entry.model.count    // undefined or null where nothing is counted
        readonly property bool counted: (count !== undefined && count !== null
                                         && (root.counts || entry.model.key === ""))
        readonly property bool lit: entry.highlighted || entry.row === root.dropRow    // Houdini's selection
        readonly property bool held: entry.pressed || move.active
        onHeldChanged: if (held) root.holder = entry; else if (root.holder === entry) root.holder = null

        leftMargin: root.drawn.bar_x * 2 + root.drawn.bar    // Houdini's tree starts after the bar
        // Houdini's QML arrow takes this colour; its widget trees draw it in primary (parts.drawTreeBranch)
        effectiveTextColor: entry.lit ? entry.background.fg : Theme.primary
        background: RowGround {
            highlighted: entry.lit
            failed: entry.lost
            alternate: root.alternatingRows && entry.row % 2 === 1
        }
        contentItem: IconLabel {    // Houdini's label; the name and its count, as the widget panel's
            height: entry.rowHeight
            alignment: Qt.AlignLeft | Qt.AlignVCenter
            mirrored: entry.mirrored
            text: entry.counted ? `${entry.model.display} (${entry.count})` : entry.model.display
            font: entry.font
            color: entry.background.fg
        }

        DragOut {    // a row dragged between rows moves; dropped on a row it does nothing
            id: move
            onStarted: root.rowDragged(root.index(entry.row, 0))
        }
        Rectangle {    // Houdini's insert line, as its Context Options rows draw it: a dragged row goes here
            readonly property bool above: entry.row === root.gapRow
            visible: above || (entry.row === root.rows - 1 && root.gapRow === root.rows)    // or below the last
            x: 8
            y: above ? -height / 2 : entry.height - height / 2
            z: 10
            width: entry.width - 16
            height: 3
            radius: 1.5
            color: Theme.highlight
            Rectangle {    // its dot at the left end
                anchors.verticalCenter: parent.verticalCenter
                width: 7
                height: 7
                radius: 3.5
                color: Theme.highlight
            }
        }
        Rectangle {    // the row's colour bar, where G01 draws it
            x: root.drawn.bar_x
            y: root.drawn.bar_inset
            width: root.drawn.bar
            height: entry.height - 2 * root.drawn.bar_inset
            color: entry.model.colour || "transparent"
        }
        PhosphorIcon {    // Houdini's warning in the arrow's place: the folder cannot be opened
            visible: entry.lost
            x: entry.leftMargin + entry.depth * entry.indentation
            width: 16    // the width of Houdini's arrow
            height: entry.height
            pixelSize: 12
            symbol: PhosphorGlyphs.warning
            color: Theme.yellow
        }
    }
}
