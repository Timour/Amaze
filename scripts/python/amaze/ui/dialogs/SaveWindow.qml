// Save to Amaze: the section, name, category, language and tags a scene node is saved with.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

DialogRoot {
    id: root

    answer: ({section: SharedState.section, name: nameField.text, category: categoryBox.currentValue ?? "",
              tags: tagsField.text, language: SharedState.languageOn ? languageBox.currentText : ""})

    GridLayout {    // labels at the right of their column, as Houdini's Create Asset window lays out its rows
        width: parent.width
        columns: 2
        columnSpacing: 8
        rowSpacing: 4

        Text {
            text: "Section"
            color: Theme.label
            Layout.alignment: Qt.AlignRight
        }
        MenuBox {
            id: sectionBox
            Layout.fillWidth: true
            model: SharedState.sections
            textRole: "text"
            valueRole: "value"
            currentIndex: SharedState.sectionRow
            enabled: SharedState.sections.length > 1
            onActivated: SharedState.chooseSection(currentValue)    // the categories follow it
            onEntered: root.accept()
        }
        Text {
            text: "Name"
            color: Theme.label
            Layout.alignment: Qt.AlignRight
        }
        TextField {
            id: nameField
            Layout.fillWidth: true
            text: SharedState.question.name
            enabled: SharedState.question.nameEnabled    // off for a save of several nodes
            ToolTip.text: SharedState.nameTip
            ToolTip.visible: hovered
            ToolTip.delay: Config.toolTipDelay
            onEntered: root.accept()
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
            model: SharedState.categories
            textRole: "text"
            valueRole: "value"
            currentIndex: SharedState.categoryRow
            onEntered: root.accept()
        }
        Text {
            text: "Language"
            color: Theme.label
            Layout.alignment: Qt.AlignRight
        }
        MenuBox {
            id: languageBox
            Layout.fillWidth: true
            model: SharedState.languages
            currentIndex: SharedState.languageRow
            enabled: SharedState.languageOn    // only for a section that stores one
            onEntered: root.accept()
        }
        Text {
            text: "Tags"
            color: Theme.label
            Layout.alignment: Qt.AlignRight
        }
        TextField {
            id: tagsField
            Layout.fillWidth: true
            onEntered: root.accept()
            onCanceled: root.reject()
        }
    }

    Component.onCompleted: (sectionBox.enabled ? sectionBox : nameField.enabled ? nameField : categoryBox)
        .forceActiveFocus()    // the first row that takes input, as a dialog's first field
}
