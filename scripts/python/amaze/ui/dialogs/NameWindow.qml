// The Name window: one name, asked for by a menu row; OK or Return hands it on, Cancel or Esc does not.
import QtQuick
import "../shared"

DialogRoot {
    id: root

    answer: form.text

    NameForm {
        id: form
        width: parent.width
        text: SharedState.question.text
        onAccepted: root.accept()
        onCanceled: root.reject()
        Component.onCompleted: form.forceActiveFocus()    // the keys go to the field, its text as it is
    }
}
