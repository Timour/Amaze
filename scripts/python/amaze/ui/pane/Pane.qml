// The Amaze (QML) pane: toolbar, section tabs, progress line, the sidebar and the grid's area.
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

        SplitView {    // Houdini's split: the sidebar at its kept width, then the grid's area
            splitColor: Theme.bg    // inside a pane, as Houdini's style draws it; paneDivider is between panes
            Layout.fillWidth: true
            Layout.fillHeight: true
            onResizingChanged: if (!resizing) SharedState.keepSidebarWidth(sidebarArea.width)

            Rectangle {    // the list's own ground below its rows, as Houdini's lists have
                id: sidebarArea
                visible: SharedState.sidebarShown
                color: Theme.viewSurface
                SplitView.preferredWidth: SharedState.sidebarWidth
                SplitView.maximumWidth: SharedState.sidebar.width    // never wider than G01, as the widget's

                SidebarTree {
                    id: sidebar
                    anchors.fill: parent
                    model: SharedState.sidebarModel
                    selectionModel: SharedState.sidebarSelection
                    counts: SharedState.sidebarCounts
                    drawn: SharedState.sidebar
                    onRowChosen: index => SharedState.chooseSidebarRow(index)
                    onStepped: SharedState.stepSidebar()

                    Connections {
                        target: SharedState
                        function onSidebarOpened(index) {
                            sidebar.open(index)
                        }
                    }
                }
            }
            Item {    // the grid's area; the grid, info and comments come in later steps
                SplitView.fillWidth: true

                EmptyState {
                    anchors.centerIn: parent
                    width: parent.width - 48    // the widget panel's empty page keeps 24 px each side
                }
            }
        }
    }
}
