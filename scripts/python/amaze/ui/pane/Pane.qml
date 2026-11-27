// The Amaze pane: toolbar, section tabs, progress line, the sidebar and the grid's area.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

PaneRoot {
    id: root

    function openMenu(rows, under, at) {    // every menu of the pane: below `under`, at screen point `at`, or the cursor
        if (rows.length === 0)
            return null
        const menu = menuMaker.createObject(root)
        if (under)
            menu.showUnder(rows, under)
        else if (at)
            menu.showAt(rows, at)
        else
            menu.show(rows)
        return menu
    }
    function onSidebar(x, y) {    // (x, y) in the pane's widget as a point in the sidebar, null off it
        if (!sidebarArea.visible)
            return null
        const side = root.mapToItem(sidebar, x, y)
        return side.x >= 0 && side.y >= 0 && side.x <= sidebar.width && side.y <= sidebar.height ? side : null
    }
    function sidebarIndexAt(x, y) {    // the sidebar row at (x, y) in the pane's widget, invalid off it
        const side = root.onSidebar(x, y)
        return side ? sidebar.indexAt(side.x, side.y) : sidebar.index(-1, 0)
    }
    function sidebarGapAt(x, y) {    // the sidebar's gap at (x, y) in the pane's widget, null off it
        const side = root.onSidebar(x, y)
        return side ? sidebar.gapAt(side.x, side.y) : null
    }
    function showSidebarGap(row) {    // the gap a dragged sidebar row would go into; -1 for none
        sidebar.gapRow = row
    }
    function showSidebarDrop(index) {    // the row a dragged tile would drop on; an invalid index for none
        sidebar.dropRow = index.valid ? sidebar.rowAtIndex(index) : -1
    }
    function menuAt(x, y) {    // Qt's context menu request at (x, y), from the pane's widget: the row under it
        const side = root.onSidebar(x, y)
        if (side) {
            sidebar.forceActiveFocus(Qt.MouseFocusReason)
            root.openMenu(SharedState.sidebarMenu(sidebar.indexAt(side.x, side.y)))
            return
        }
        const shown = grid.active ? grid : list
        const view = shown.item
        if (!view || !shown.visible)
            return
        const at = root.mapToItem(view, x, y)
        if (at.x < 0 || at.y < 0 || at.x > view.width || at.y > view.height)
            return    // outside the grid's area
        view.forceActiveFocus(Qt.MouseFocusReason)
        root.openMenu(SharedState.tileMenu(view.rowAt(at.x, at.y)))
    }
    Connections {    // a menu the engine opens itself, at the cursor; one that cannot open is closed at once
        target: SharedState
        function onMenuOffered(rows, at) {
            if (!root.openMenu(rows, null, at))
                SharedState.menuClosed()
        }
    }
    Component {
        id: menuMaker
        AmazeMenu {
            onPicked: key => SharedState.pickMenu(key)
            onFinished: SharedState.menuClosed()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Toolbar {
            Layout.fillWidth: true
            onMenuAsked: (rows, under) => under.menu = root.openMenu(rows, under)
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
            Rectangle {    // the strip's bottom row, drawn over the tab bar
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
            onResizingChanged: {
                if (resizing)
                    return
                SharedState.keepSidebarWidth(sidebarArea.width)
                if (side.visible)
                    SharedState.keepSidePaneWidth(side.width)
            }

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
                    drawn: SharedState.sidebar
                    onStepped: SharedState.stepSidebar()
                    onRowDragged: index => SharedState.dragSidebarRow(index)

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
                        drawn: SharedState.tile
                        badges: SharedState.badges
                        marks: SharedState.marks
                        onTileClicked: (row, modifiers) => SharedState.clickTile(row, modifiers)
                        onTileDoubleClicked: row => SharedState.doubleClickTile(row)
                        onTileKeyed: (row, modifiers) => SharedState.keyTile(row, modifiers)
                        onBadgeClicked: (row, name) => SharedState.clickBadge(row, name)
                        onTileDragged: (row, modifiers) => SharedState.dragTile(row, modifiers)
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
                        drawn: SharedState.table
                        sortColumn: SharedState.sortColumn
                        descending: SharedState.sortDescending
                        ink: colour => SharedState.listInk(colour)
                        onRowClicked: (row, modifiers) => SharedState.clickTile(row, modifiers)
                        onRowDoubleClicked: row => SharedState.doubleClickTile(row)
                        onRowKeyed: (row, modifiers) => SharedState.keyTile(row, modifiers)
                        onHeadingClicked: column => SharedState.sortList(column)
                        onRowDragged: (row, modifiers) => SharedState.dragTile(row, modifiers)
                    }
                }
                EmptyState {
                    anchors.centerIn: parent
                    width: parent.width - 48    // the empty page keeps 24 px each side
                }
            }
            Item {    // right of the grid, at its kept width: the Info or the Comments pane, one at a time
                id: side
                visible: SharedState.infoShown || SharedState.commentsShown
                SplitView.preferredWidth: SharedState.sidePaneWidth
                SplitView.minimumWidth: SharedState.sidePaneLeast

                InfoPane {
                    anchors.fill: parent
                    visible: SharedState.infoShown
                }
                CommentsPane {
                    anchors.fill: parent
                    visible: SharedState.commentsShown
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
