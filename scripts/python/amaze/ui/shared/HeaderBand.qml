// The band over a pane: its icon, a name in bold and a type, then the buttons it is given.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui

Rectangle {
    id: root

    property var drawn: ({})    // the frame's figures: header, pad, gap, icon, right_pad
    property string icon: ""    // the art's file name in ui/
    property color iconColor: "transparent"    // fills the art; transparent keeps its own colours
    property real iconOpacity: 1
    property string name: ""
    property string type: ""
    property real textOpacity: 1
    default property alias buttons: row.data    // the band's buttons, right of the type

    implicitHeight: root.drawn.header

    RowLayout {    // one row; every item is centred in the drawn height
        id: row
        anchors.fill: parent
        anchors.leftMargin: root.drawn.pad
        anchors.rightMargin: root.drawn.right_pad
        spacing: root.drawn.gap

        AmazeIcon {
            Layout.preferredWidth: root.drawn.icon
            Layout.preferredHeight: root.drawn.icon
            file: root.icon
            color: root.iconColor
            opacity: root.iconOpacity
        }
        Label {
            text: root.name
            textFormat: Text.PlainText    // a name on disk, not markup
            font.bold: true
            color: Theme.fg
            opacity: root.textOpacity
        }
        Label {
            Layout.fillWidth: true    // takes the free space
            text: root.type
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: Theme.secondarySurfaceFg
            opacity: root.textOpacity
        }
    }
}
