// Every table: Qt's TableView under Houdini's header, in its ScrollView; whole rows highlighted.
import QtQuick
import houdini.pluto
import houdini.ui

Item {
    id: root

    property alias model: view.model    // set before `selectionModel`: Qt points a selection at its rows
    property alias selectionModel: view.selectionModel
    property var columns: []    // per model column: its starting width, 0 to hide it, and if a tick
    property var drawn: ({})    // `amazetheme.drawn_list`: the header's height, the text inset, the tick
    property int sortColumn: -1    // the heading drawn sorted; -1 for none
    property bool descending: false
    property var ink: colour => colour    // a cell's own text colour as it is drawn
    property bool wheelFix: false    // the wheel as Houdini's Context Options list takes it; off, Qt's
    signal rowClicked(int row, int modifiers)    // the user's click; row -1 is the space below the rows
    signal headingClicked(int column)

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
        height: root.drawn.header_h
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

    ScrollView {
        anchors.fill: parent
        anchors.topMargin: header.height

        TableView {
            id: view

            clip: true
            pointerNavigationEnabled: false    // Qt's own click only makes a row current: `rowClicked` selects
            keyNavigationEnabled: false    // the keys come with a later step, as in the grid
            columnWidthProvider: column => root.widthOf(column)
            onWidthChanged: forceLayout()

            WheelScroll {
                view: view
                enabled: root.wheelFix
            }
            RowStripes {
                view: view
            }
            Item {    // under the rows and the space below them, so one handler takes every click
                parent: view.contentItem
                z: -2
                width: Math.max(view.width, view.contentWidth)
                height: Math.max(view.height, view.contentHeight)
                TapHandler {
                    onTapped: root.rowClicked(view.cellAtPosition(point.position).y, point.modifiers)
                }
            }

            delegate: RowGround {
                id: cell

                required property var model
                required property int row
                required property int column
                required property bool selected
                readonly property bool tick: column < root.columns.length && root.columns[column].tick

                highlighted: selected
                alternate: view.alternatingRows && row % 2 === 1
                clip: true

                Text {
                    visible: !cell.tick
                    x: root.drawn.text_inset
                    width: parent.width - x
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    color: cell.highlighted || !cell.model.foreground ? cell.fg : root.ink(cell.model.foreground)
                    text: cell.model.display ?? ""
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
