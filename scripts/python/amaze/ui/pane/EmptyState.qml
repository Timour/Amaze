// The grid's empty state: the engine's words and their button, in the middle of the grid's area.
import QtQuick
import houdini.pluto
import houdini.ui

Column {
    id: root

    visible: SharedState.emptyHeadline !== ""
    spacing: 8

    Text {
        width: root.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        size: Typography.large
        font.bold: true
        text: SharedState.emptyHeadline
    }
    Text {
        width: root.width
        visible: text !== ""
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        text: SharedState.emptySentence
    }
    Button {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: text !== ""
        text: SharedState.emptyButton
        onClicked: SharedState.pressEmptyButton()
    }
}
