// Save Code to Amaze and Edit Snippet: a snippet's name, language, category, tags and code.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

DialogRoot {
    id: root

    fills: true    // the code takes the window's height, which the user sets
    okText: ""
    applyText: SharedState.applyText    // Apply saves and keeps the window; Cancel keeps what it saved
    answer: ({name: nameField.text, language: languageBox.currentText, category: categoryBox.currentValue ?? "",
              tags: tagsField.text, code: codeField.text})

    ColumnLayout {
        width: parent.width
        height: parent.height
        spacing: 12

        GridLayout {    // two columns of rows, each label at the right of its own
            Layout.fillWidth: true
            columns: 4
            columnSpacing: 8
            rowSpacing: 4

            Text {
                text: "Name"
                color: Theme.label
                Layout.alignment: Qt.AlignRight
            }
            TextField {
                id: nameField
                Layout.fillWidth: true
                Layout.horizontalStretchFactor: 1
                text: SharedState.question.name
                ToolTip.text: SharedState.nameTip
                ToolTip.visible: hovered
                ToolTip.delay: Config.toolTipDelay
                onCanceled: root.reject()    // Esc in Houdini's field
            }
            Text {
                text: "Category"
                color: Theme.label
                Layout.alignment: Qt.AlignRight
            }
            MenuBox {    // a list, not a field: a category is made in the sidebar
                id: categoryBox
                Layout.fillWidth: true
                Layout.horizontalStretchFactor: 1
                model: SharedState.categories
                textRole: "text"
                valueRole: "value"
                currentIndex: SharedState.categoryRow
            }
            Text {
                text: "Language"
                color: Theme.label
                Layout.alignment: Qt.AlignRight
            }
            MenuBox {
                id: languageBox
                Layout.fillWidth: true
                Layout.horizontalStretchFactor: 1
                model: SharedState.languages
                currentIndex: SharedState.languageRow
            }
            Text {
                text: "Tags"
                color: Theme.label
                Layout.alignment: Qt.AlignRight
            }
            TextField {
                id: tagsField
                Layout.fillWidth: true
                Layout.horizontalStretchFactor: 1
                text: SharedState.question.tags
                onCanceled: root.reject()
            }
        }
        CodeField {
            id: codeField
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: SharedState.question.code
            language: SharedState.highlighter    // the snippet's language as it opened: Houdini's own
            ground: SharedState.codeGround || Theme.field
        }
    }

    Component.onCompleted: nameField.forceActiveFocus()    // the first field, as the dialog's
}
