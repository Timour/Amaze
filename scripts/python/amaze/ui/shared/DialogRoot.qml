// The root of every Amaze dialog window, as Houdini's Create Asset window: its rows, then OK and Cancel.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui

Item {
    id: root

    default property alias content: rows.data    // the kind's rows, top to bottom, each as wide as the window
    property var answer: null    // what OK hands on: each kind binds it to its fields

    function accept() {    // OK, and Return in a field
        SharedState.accept(root.answer)
    }
    function reject() {    // Cancel, as Esc and the window's own close
        SharedState.reject()
    }

    anchors.fill: parent
    focus: true
    Keys.onEscapePressed: root.reject()

    ScaledContent {
        Column {
            x: 8
            width: parent.width - 16
            topPadding: 8
            bottomPadding: 8
            spacing: 12

            onHeightChanged: SharedState.contentHeightChanged(height)    // the window takes this height

            Column {
                id: rows
                width: parent.width
                spacing: 4
            }
            RowLayout {    // Houdini's order: the primary button, then Cancel, at the right
                width: parent.width
                spacing: 8

                Item {
                    Layout.fillWidth: true
                }
                Button {
                    text: "OK"
                    primary: true
                    implicitWidth: 80
                    onClicked: root.accept()
                }
                Button {
                    text: "Cancel"
                    implicitWidth: 80
                    onClicked: root.reject()
                }
            }
        }
    }
}
