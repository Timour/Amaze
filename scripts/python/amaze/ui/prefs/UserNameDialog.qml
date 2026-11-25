// Create User and Rename User: the one Name field, as Houdini's Save Query dialog asks for a name.
import QtQuick
import houdini.pluto
import houdini.ui
import "../shared"

Dialog {
    id: root

    property alias name: form.text

    implicitWidth: 300
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    standardButtons: Dialog.Ok | Dialog.Cancel
    contentItem: NameForm {
        id: form
        onAccepted: root.accept()
        onCanceled: root.reject()
    }
    onAboutToShow: form.forceActiveFocus()
    onAboutToHide: form.focus = false
}
