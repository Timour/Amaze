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
    signal stepped()    // a key that Qt's own navigation moves the current row by; no other key
    readonly property var steps: [Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                                  Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End]

    clip: true
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

        leftMargin: root.drawn.bar_x * 2 + root.drawn.bar    // Houdini's tree starts after the bar
        // Houdini's QML arrow takes this colour; its widget trees draw it in primary (parts.drawTreeBranch)
        effectiveTextColor: entry.highlighted ? entry.background.fg : Theme.primary
        background: RowGround {
            highlighted: entry.highlighted
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
