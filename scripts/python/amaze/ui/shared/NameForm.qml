// The one name field: its label, then Houdini's field; Return gives `accepted`, Esc in it `canceled`.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui

FocusScope {    // focus given to the form goes to its field, and taken from the form leaves the field
    id: form

    property string label: "Name"
    property alias text: field.text    // as typed: a cleared field is ""
    signal accepted()
    signal canceled()

    implicitWidth: row.implicitWidth
    implicitHeight: row.implicitHeight

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: 8

        Text {
            text: form.label
            color: Theme.label
        }
        TextField {
            id: field
            Layout.fillWidth: true
            focus: true
            onEntered: form.accepted()    // Houdini's field: Return and Enter
            onCanceled: form.canceled()    // Houdini's field: Esc
        }
    }
}
