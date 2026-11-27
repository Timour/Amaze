// The one drop-down menu: Qt's ComboBox drawn as Houdini's, its list scrolling beside a bar.
import QtQuick
import QtQuick.Templates as T
import houdini.pluto
import houdini.ui

T.ComboBox {
    id: root

    property string enabledRole: ""    // the role that greys a row where it is false; "" for no such role
    readonly property color textColor: !root.enabled ? Theme.dimFg : root.down ? Theme.pressedFg
                                       : root.hovered ? Theme.buttonFg : Theme.fg
    readonly property Item menuRow: MenuRow {    // never drawn: a row's height
        text: " "
    }

    implicitWidth: implicitBackgroundWidth
    implicitHeight: implicitBackgroundHeight
    leftPadding: 4 + indicator.width
    rightPadding: 4
    font.pixelSize: Typography.medium

    delegate: MenuRow {    // a click on a greyed row picks nothing
        required property var model
        required property int index

        width: ListView.view.width
        text: model[root.textRole]
        enabled: root.enabledRole === "" || !!model[root.enabledRole]
        font.weight: root.currentIndex === index ? Font.DemiBold : Font.Normal
        highlighted: root.highlightedIndex === index
        hoverEnabled: root.hoverEnabled
    }

    indicator: Item {
        implicitWidth: 18
        height: root.height

        Rectangle {
            anchors.fill: parent
            visible: root.enabled && !root.hovered && !root.down
            color: Theme.button
            topLeftRadius: 4
            bottomLeftRadius: 4
            opacity: 0.99    // as Houdini's: Qt 6.8 draws single corner radii wrong at 1
        }
        PhosphorIcon {
            anchors.fill: parent
            color: Qt.alpha(root.textColor, root.enabled ? 1.0 : 0.3)
            symbol: PhosphorGlyphs.caret_up_down
            pixelSize: 12
        }
    }

    contentItem: T.TextField {    // the picked row's text; Amaze's drop-downs take no typing
        color: root.textColor
        text: root.displayText
        enabled: false
        readOnly: true
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        implicitWidth: 60
        implicitHeight: 22
        radius: 4
        color: root.down ? Theme.pressed : !root.enabled ? Qt.alpha(Theme.button, 0.15)
               : root.hovered ? Theme.button : Theme.fieldButton
    }

    popup: Popup {    // Houdini's Popup, which scales as Houdini's windows do
        id: list

        readonly property real row: root.menuRow.implicitHeight * list._scale

        y: root.height
        popupType: Platforms.comboBoxType
        implicitWidth: root.width * list._scale
        // no taller than the menu's window, as Qt's own drop-downs ▸r/qml-combobox-menu-and-the-screen
        implicitHeight: Math.min(root.count, Math.floor(root.Window.height / list.row)) * list.row
        margins: 0
        padding: 0

        contentItem: Item {
            ListView {
                id: rows

                width: list.width / list._scale - (bar.visible ? bar.width : 0)    // rows end at the bar
                height: list.height / list._scale    // the size before the popup's own scale
                clip: true
                interactive: false    // no drag scrolling, as Houdini's lists
                model: list.visible ? root.delegateModel : null    // rows exist while the list is open
                currentIndex: root.highlightedIndex
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar {
                    id: bar

                    parent: rows.parent    // beside the rows
                    x: rows.width
                    height: rows.height
                    visible: size < 1.0    // as `ScrollArea` shows its bars, for a bar with no ScrollView
                }
                WheelScroll {
                    view: rows
                }
            }
        }
        background: Rectangle {    // as Houdini's ComboBox draws its list
            width: list.width / list._scale
            height: list.height / list._scale
            radius: 4
            color: Theme.menuSurface
            border.color: Theme.divider

            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 3
                color: "transparent"
                border.color: Qt.alpha(Theme.dimFg, 0.5)
            }
        }
    }

    Timer {    // as Houdini's ComboBox: the press on the menu that closed its list does not open it again
        id: closing

        interval: 25
        onTriggered: guard.enabled = false
    }
    MouseArea {
        id: guard

        anchors.fill: parent
        enabled: false
        onPressed: event => event.accepted = true
    }
    Connections {
        target: root.popup

        function onVisibleChanged() {
            if (!root.popup.visible) {
                guard.enabled = true
                closing.restart()
            }
        }
    }
}
