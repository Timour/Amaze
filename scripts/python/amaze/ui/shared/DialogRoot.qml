// The root of every Amaze dialog window, as Houdini's Create Asset window: its rows, then OK and Cancel.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui

Item {
    id: root

    default property alias content: rows.data    // the kind's rows, top to bottom, each as wide as the window
    property var answer: null    // what OK hands on: each kind binds it to its fields
    property string okText: "OK"    // the primary button's word, as the kind's frame names it; "" for none
    property bool okEnabled: true    // off while the kind has nothing to hand on
    property string applyText: ""    // a button that hands the answer on and keeps the window, as Houdini's Apply
    property string cancelText: "Cancel"    // "" where the kind's frame draws none: its window's close cancels
    property bool fills: false    // the rows take the height the window is given, not the window theirs
    property string extraText: ""    // a button after the primary one that hands on `extraAnswer` and keeps the window
    property var extraAnswer: null
    property bool extraEnabled: true
    property real buttonWidth: 80    // each button's width, as the kind's frame draws it
    property real okWidth: buttonWidth    // the primary button's, where its frame draws the buttons unalike
    property real extraWidth: buttonWidth
    property real cancelWidth: buttonWidth
    property real buttonGap: 8    // between two buttons
    property real marginTop: 8    // over the rows
    property real rowsGap: 12    // between the rows and the buttons
    property real marginBottom: 8    // under the buttons

    function accept() {    // OK, and Return
        if (root.okText !== "" && root.okEnabled)
            SharedState.accept(root.answer)
    }
    function apply() {
        SharedState.apply(root.answer)
    }
    function reject() {    // Cancel, as Esc and the window's own close
        SharedState.reject()
    }

    anchors.fill: parent
    focus: true
    Keys.onEscapePressed: root.reject()
    Keys.onReturnPressed: root.accept()    // the primary button is the default one, as a dialog's
    Keys.onEnterPressed: root.accept()

    ScaledContent {
        Column {
            id: column
            x: 8
            width: parent.width - 16
            height: root.fills ? parent.height : implicitHeight
            topPadding: root.marginTop
            bottomPadding: root.marginBottom
            spacing: root.rowsGap

            onHeightChanged: {
                if (!root.fills)
                    SharedState.contentHeightChanged(height)    // the window takes this height
            }

            Column {
                id: rows
                width: parent.width
                height: (root.fills ? column.height - column.topPadding - column.bottomPadding
                                      - column.spacing - buttons.height : implicitHeight)
                spacing: 4
            }
            RowLayout {    // Houdini's order: Apply, the primary button, then Cancel, at the right
                id: buttons
                width: parent.width
                spacing: root.buttonGap

                Item {
                    Layout.fillWidth: true
                }
                Button {
                    text: root.applyText
                    visible: root.applyText !== ""
                    implicitWidth: root.buttonWidth
                    onClicked: root.apply()
                }
                Button {
                    text: root.okText
                    visible: root.okText !== ""
                    primary: true
                    enabled: root.okEnabled
                    implicitWidth: root.okWidth
                    onClicked: root.accept()
                }
                Button {
                    text: root.extraText
                    visible: root.extraText !== ""
                    enabled: root.extraEnabled
                    implicitWidth: root.extraWidth
                    onClicked: SharedState.apply(root.extraAnswer)
                }
                Button {
                    text: root.cancelText
                    visible: root.cancelText !== ""
                    implicitWidth: root.cancelWidth
                    onClicked: root.reject()
                }
            }
        }
    }
}
