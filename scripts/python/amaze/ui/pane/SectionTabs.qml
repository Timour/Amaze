// The section tabs: Houdini's own TabBar and TabButton, each section's art where its frame draws it.
import QtQuick
import houdini.pluto
import houdini.ui
import "../shared"

Item {
    id: root

    // [{label, icon, width, height, artX, artY, artWidth, artHeight}] from `section_tab_rows`: the
    // art's drawn box, 2 px from the name, and its file's own box, which reaches past it by its outline
    property var tabs: []
    property int currentIndex: 0    // the tab shown checked, also when the tabs are made again
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
                checked: index === root.currentIndex    // the TabBar's own index follows its checked tab
                onClicked: root.tabChosen(index)
                Rectangle {    // Houdini's widget tabs' hover (pluto parts.drawTabShape); its QML tab has none
                    parent: tab.background
                    anchors.fill: parent
                    radius: parent.radius
                    color: Qt.rgba(1, 1, 1, 0.05)
                    visible: tab.enabled && tab.hovered && !tab.checked
                }
                // Houdini's tab, with its own chip, padding and text colours; the art is drawn as
                // drawn (Houdini's icon renderer makes square, re-tinted icons), 2 px from the name
                contentItem: Item {
                    readonly property var row: tab.modelData
                    implicitWidth: (row.icon ? row.width + 2 : 0) + label.implicitWidth
                    implicitHeight: label.implicitHeight    // the outline's room adds no height
                    AmazeIcon {
                        visible: parent.row.icon !== ""
                        file: parent.row.icon
                        x: parent.row.artX
                        y: Math.round((parent.height - parent.row.height) / 2) + parent.row.artY
                        width: parent.row.artWidth
                        height: parent.row.artHeight
                    }
                    Text {
                        id: label
                        x: parent.row.icon ? parent.row.width + 2 : 0
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
