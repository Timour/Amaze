// The Versions window: a material's versions, newest first; Select or Delete hands on the one picked.
import QtQuick
import houdini.pluto
import houdini.ui
import "../shared"

DialogRoot {
    id: root

    okText: SharedState.selectText
    okEnabled: SharedState.picked >= 0
    answer: SharedState.picked
    extraText: SharedState.deleteText
    extraEnabled: SharedState.picked >= 0 && SharedState.deletable
    extraAnswer: ({"delete": SharedState.picked})
    extraTip: SharedState.deleteTip
    okWidth: SharedState.frame.widths[0]
    extraWidth: SharedState.frame.widths[1]
    cancelWidth: SharedState.frame.widths[2]
    buttonGap: SharedState.frame.between
    marginTop: SharedState.frame.top
    rowsGap: SharedState.frame.over
    marginBottom: SharedState.frame.bottom

    TextMetrics {    // a day as the list draws it: the date column is as wide as one, the name the rest
        id: day
        font.family: Typography.defaultFamily
        font.pixelSize: Typography.medium
        text: "0000-00-00"
    }
    Item {    // the list, its tip shown anywhere over it
        width: parent.width
        height: SharedState.listHeight
        ToolTip.text: SharedState.tip
        ToolTip.visible: over.hovered
        ToolTip.delay: Config.toolTipDelay

        HoverHandler {
            id: over
        }
        RowsTable {
            id: table
            anchors.fill: parent
            headings: false
            ownKeys: true
            model: SharedState.rows    // first: a selection set before it is cleared by Qt
            selectionModel: SharedState.selection
            columns: {
                const date = Math.ceil(day.advanceWidth) + 2 * SharedState.table.text_inset
                return [{width: Math.max(1, width - date), tick: false}, {width: date, tick: false}]
            }
            drawn: SharedState.table
            onRowClicked: row => SharedState.pick(row)
            onRowKeyed: row => SharedState.pick(row)
            Component.onCompleted: table.forceActiveFocus()    // the arrows move the pick at once
        }
    }
}
