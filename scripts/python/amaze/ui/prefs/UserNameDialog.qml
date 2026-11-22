// Create User and Rename User: one Name field, as Houdini's Save Query dialog asks for a name.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui

Dialog {
    id: root

    property alias name: nameField.text

    implicitWidth: 300
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    standardButtons: Dialog.Ok | Dialog.Cancel
    contentItem: RowLayout {
        spacing: 8

        Text {
            text: "Name"
            color: Theme.label
        }
        TextField {
            id: nameField
            Layout.fillWidth: true
            Keys.onReturnPressed: root.accept()
        }
    }
    onAboutToShow: nameField.forceActiveFocus()
    onAboutToHide: nameField.focus = false
}
