// The section tabs: Houdini's own TabBar and TabButton, each section's art at its drawn size.
import QtQuick
import houdini.pluto
import houdini.ui

Item {
    id: root

    // [{label, icon, iconWidth, iconHeight, bleed}], set by SectionTabBar; bleed is the room
    // around the art for its outline, so the art itself starts at the padding, 2 px from the name
    property var tabs: []
    property alias currentIndex: bar.currentIndex
    signal tabChosen(int index)

    implicitWidth: bar.implicitWidth
    implicitHeight: bar.implicitHeight

    function tabRect(index) {
        const tab = bar.itemAt(index)
        if (!tab) {
            return Qt.rect(0, 0, 0, 0)
        }
        const at = tab.mapToItem(root, 0, 0)
        return Qt.rect(at.x, at.y, tab.width, tab.height)
    }

    TabBar {
        id: bar

        Repeater {
            model: root.tabs
            delegate: TabButton {
                id: tab
                required property int index
                required property var modelData
                text: modelData.label
                width: implicitWidth    // as Houdini's parameter pane sizes its tabs
                onClicked: root.tabChosen(index)
                // Houdini's tab, with its own chip, padding and text colours; the art is drawn as
                // drawn (Houdini's icon renderer makes square, re-tinted icons), 2 px from the name
                contentItem: Item {
                    readonly property real art: tab.modelData.icon ? tab.modelData.iconWidth - 2 * tab.modelData.bleed : 0
                    implicitWidth: (art ? art + 2 : 0) + label.implicitWidth
                    implicitHeight: label.implicitHeight    // the outline's room adds no height
                    Image {
                        visible: tab.modelData.icon !== ""
                        source: tab.modelData.icon
                        x: -tab.modelData.bleed    // the art itself starts at the padding
                        y: Math.round((parent.height - height) / 2)
                        width: tab.modelData.iconWidth
                        height: tab.modelData.iconHeight
                        sourceSize: Qt.size(width * Screen.devicePixelRatio, height * Screen.devicePixelRatio)
                        smooth: false
                    }
                    Text {
                        id: label
                        x: parent.art ? parent.art + 2 : 0
                        anchors.verticalCenter: parent.verticalCenter
                        text: tab.text
                        font: tab.font
                        color: tab.checked ? Theme.checkedSurfaceFg : Theme.secondarySurfaceFg
                    }
                }
            }
        }
    }
}
