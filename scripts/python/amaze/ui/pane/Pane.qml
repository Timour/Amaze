// The Amaze (QML) pane: toolbar, section tabs, progress line, and the area the grid will fill.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

PaneRoot {
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Toolbar {
            Layout.fillWidth: true
        }

        Item {    // the strip: the tabs on its bottom row at S01's left edge, Cancel at the right
            Layout.fillWidth: true
            Layout.preferredHeight: SharedState.strip.height

            SectionTabs {
                id: tabs
                x: SharedState.strip.left
                anchors.bottom: parent.bottom
                width: Math.min(implicitWidth, parent.width - x)
                tabs: SharedState.tabs
                currentIndex: SharedState.currentTab
                onTabChosen: index => SharedState.chooseTab(index)
            }
            Rectangle {    // the strip's bottom row over the tab bar, as the widget panel's strip draws it
                id: line
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.surfaceLowest
            }
            Button {
                anchors.right: parent.right
                anchors.rightMargin: 8    // as S03 draws it
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -line.height / 2
                visible: SharedState.progressShown && x >= tabs.x + tabs.implicitWidth + 8    // never over a tab
                text: SharedState.words.cancel
                onClicked: SharedState.cancelWork()
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            visible: SharedState.progressShown
            from: 0
            to: Math.max(SharedState.progressTotal, 1)
            value: SharedState.progressDone
        }

        Item {    // the grid's area; the sidebar, grid, info and comments come in later steps
            Layout.fillWidth: true
            Layout.fillHeight: true

            EmptyState {
                anchors.centerIn: parent
                width: parent.width - 48    // the widget panel's empty page keeps 24 px each side
            }
        }
    }
}
