// Houdini's ToolButton with Amaze's art, its tip and its dimming, and B01c's chip while on or open.
import QtQuick
import houdini.pluto
import houdini.ui
import "../shared"

ToolButton {
    id: button

    property var drawn: SharedState.toolbar    // `amazetheme.drawn_toolbar`: the chip's colours, B01's art
    property string art: ""
    property string node: ""    // its name in B01, which gives the art's size and place
    property real artSize: button.drawn.icons[button.node] ?? 0
    property var artAt: button.drawn.icon_at[button.node]    // the art's place in the button, or centred
    property color artColor: "transparent"
    property string tip: ""
    property string opens: ""    // the menu a press opens below it, by the name its owner gives it
    property QtObject menu: null    // that menu while it is open; Qt clears it when the menu goes
    property bool on: checked || menu !== null    // B01c's on state: a toggle on, a menu or window open
    // a menu's window takes its button's release: a menu button stays held ▸r/qml-menu-press
    readonly property bool held: down && opens === ""

    signal menuAsked(string name)    // a press on a menu button: its owner opens the menu

    flat: true
    padding: 0    // the art sits where B01 draws it inside the button, not inside Houdini's padding
    implicitWidth: button.drawn.button
    implicitHeight: button.drawn.button
    opacity: enabled ? 1.0 : Theme.disabledAlpha
    layer.enabled: !enabled    // dimmed as one picture, or the chip would show through the art
    ToolTip.text: button.tip
    ToolTip.visible: SharedState.tipsShown && button.hovered && button.tip !== ""
    ToolTip.delay: Config.toolTipDelay
    onPressed: if (button.opens !== "") button.menuAsked(button.opens)
    background: Item {
        Rectangle {    // B01c's chip: its grey middle, Houdini's checked border and ring
            anchors.fill: parent
            visible: button.on || button.held
            radius: 4
            color: button.drawn.on.fill
            border.color: button.drawn.on.border
            border.width: 1
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 3
                color: "transparent"
                border.color: button.drawn.on.ring
                border.width: 1.5
            }
        }
        Rectangle {    // Houdini's tool-button hover (pluto parts.drawButtonPanel): white at 10%
            anchors.fill: parent
            visible: button.hovered && button.enabled && !button.on && !button.held
            radius: 4
            color: Qt.rgba(1, 1, 1, 0.1)
            border.color: Qt.rgba(1, 1, 1, 0.145)    // its pen over its fill, measured #4c4c4c at 1x
            border.width: 1
        }
    }
    contentItem: Item {
        AmazeIcon {
            file: button.art
            width: button.artSize
            height: width
            x: button.artAt ? button.artAt.x : Math.floor((parent.width - width) / 2)
            y: button.artAt ? button.artAt.y : Math.floor((parent.height - height) / 2)
            color: button.artColor
        }
    }
}
