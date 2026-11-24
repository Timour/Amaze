// The Amaze (QML) pane: toolbar, section tabs, progress line, the sidebar and the grid's area.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

PaneRoot {
    id: root

    function openMenu(rows) {    // every right-click menu of the pane: the engine's rows, at the cursor
        if (rows.length > 0)
            menuMaker.createObject(root).show(rows)
    }
    Component {
        id: menuMaker
        AmazeMenu {
            onPicked: key => SharedState.pickMenu(key)
        }
    }

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

        SplitView {    // Houdini's split: the sidebar at its kept width, then the grid's area
            id: content
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
                // Qt 6.8.3's tree leaves its own moves unaccepted (Qt fixed it later): they end here
                Keys.onPressed: event => event.accepted = sidebar.steps.includes(event.key)

                SidebarTree {
                    id: sidebar
                    anchors.fill: parent
                    model: SharedState.sidebarModel
                    selectionModel: SharedState.sidebarSelection
                    counts: SharedState.sidebarCounts
                    wheelFix: SharedState.wheelFix
                    drawn: SharedState.sidebar
                    onStepped: SharedState.stepSidebar()

                    Connections {
                        target: SharedState
                        function onSidebarOpened(index) {
                            sidebar.open(index)
                        }
                    }
                }
            }
            Item {    // the grid's area: the grid or the list of the same rows and selection, never both
                SplitView.fillWidth: true

                Connections {    // an Amaze hotkey's move goes to whichever of the two is shown
                    target: SharedState
                    function onKeyStepped(name, extend) {
                        (grid.active ? grid : list).item?.step(name, extend)
                    }
                }
                Loader {    // made only in grid mode, so a hidden grid holds no picture
                    id: grid
                    anchors.fill: parent
                    active: SharedState.viewMode !== "list"
                    visible: SharedState.emptyHeadline === ""    // an empty category is an empty grid
                    sourceComponent: TileGrid {
                        model: SharedState.gridModel
                        selectionModel: SharedState.gridSelection
                        tileSize: SharedState.tileSize
                        wheelFix: SharedState.wheelFix
                        drawn: SharedState.tile
                        badges: SharedState.badges
                        onTileClicked: (row, modifiers) => SharedState.clickTile(row, modifiers)
                        onTileDoubleClicked: row => SharedState.doubleClickTile(row)
                        onTileKeyed: (row, modifiers) => SharedState.keyTile(row, modifiers)
                        onTileMenu: row => root.openMenu(SharedState.tileMenu(row))
                        onBadgeClicked: (row, name) => SharedState.clickBadge(row, name)
                    }
                }
                Loader {
                    id: list
                    anchors.fill: parent
                    active: SharedState.viewMode === "list"
                    visible: SharedState.emptyHeadline === ""    // an empty category is an empty list
                    sourceComponent: RowsTable {
                        model: SharedState.gridModel    // first: a selection set before it is cleared by Qt
                        selectionModel: SharedState.gridSelection
                        columns: SharedState.listColumns
                        wheelFix: SharedState.wheelFix
                        drawn: SharedState.table
                        sortColumn: SharedState.sortColumn
                        descending: SharedState.sortDescending
                        ink: colour => SharedState.listInk(colour)
                        onRowClicked: (row, modifiers) => SharedState.clickTile(row, modifiers)
                        onRowDoubleClicked: row => SharedState.doubleClickTile(row)
                        onRowKeyed: (row, modifiers) => SharedState.keyTile(row, modifiers)
                        onRowMenu: row => root.openMenu(SharedState.tileMenu(row))
                        onHeadingClicked: column => SharedState.sortList(column)
                    }
                }
                EmptyState {
                    anchors.centerIn: parent
                    width: parent.width - 48    // the widget panel's empty page keeps 24 px each side
                }
            }
        }
    }

    ProgressBar {    // over the top edge of the sidebar and grid, so showing it moves nothing
        y: content.y
        width: parent.width
        visible: SharedState.progressShown
        from: 0
        to: Math.max(SharedState.progressTotal, 1)
        value: SharedState.progressDone
    }
}
