// The grid of tiles: Qt's GridView in Houdini's ScrollView, over a section's rows and selection.
import QtQuick
import houdini.pluto
import houdini.ui

ScrollView {
    id: root

    property alias model: view.model
    property var selectionModel: null    // the section's own, which Qt's selection rules move
    property real tileSize: 128    // the slider's size: the picture is this plus T01's width extra, less its pad
    property var drawn: ({})    // `drawn_tile`
    property var badges: []    // `badge_rows`
    property var marks: []    // `mark_rows`
    property bool wheelFix: false    // the wheel as Houdini's Context Options list takes it; off, Qt's
    readonly property bool hotkeysFirst: true    // Amaze's hotkeys before this ScrollView's own arrow scrolling
    signal tileClicked(int row, int modifiers)    // the user's click; row -1 is the grid's empty space
    signal tileDoubleClicked(int row)
    signal tileKeyed(int row, int modifiers)    // the user's move by an Amaze hotkey landed on `row`
    signal badgeClicked(int row, string name)
    signal tileDragged(int row, int modifiers)    // a press on tile `row` moved past the drag distance

    function rowAt(x, y) {    // the tile at (x, y) in the grid, -1 for its empty space
        const at = root.mapToItem(view.contentItem, x, y)
        return view.indexAt(at.x, at.y)
    }
    function step(name, extend) {    // an Amaze hotkey's move, by Qt's own grid moves and a page of tiles
        keys.step(name, extend, view.count, Math.max(1, Math.floor(view.height / view.cellHeight))
                  * Math.max(1, Math.floor(view.width / view.cellWidth)), view.moved)
    }

    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    background: Rectangle {
        color: root.drawn.back
    }

    GridView {
        id: view

        property int selectionChanges: 0    // counted, so every tile reads its selected state again
        property Item holder: null    // the tile under a press: no flick takes it, so a drag goes out
        // each line in whole px, as QFontMetrics gives the widget tile its cell
        readonly property int nameHeight: Math.round(nameFont.ascent) + Math.round(nameFont.descent)
        readonly property int subtitleHeight: Math.round(subtitleFont.ascent) + Math.round(subtitleFont.descent)

        clip: true
        interactive: holder === null    // Qt's documented way to hold flicking for a child's own gesture
        cacheBuffer: 0    // tiles, and their pictures, only while on screen
        keyNavigationEnabled: false    // keys are Amaze's hotkeys, landing through `step`
        cellWidth: root.tileSize + root.drawn.width_extra
        cellHeight: root.drawn.pad + cellWidth - 2 * root.drawn.pad + root.drawn.img_text_gap
                    + nameHeight + root.drawn.line_gap + subtitleHeight + root.drawn.bottom_pad

        function moved(name, from) {    // Qt's own grid move from tile `from`, -1 for one it does not take
            view.currentIndex = from
            switch (name) {
            case "left": view.moveCurrentIndexLeft(); break
            case "right": view.moveCurrentIndexRight(); break
            case "up": view.moveCurrentIndexUp(); break
            case "down": view.moveCurrentIndexDown(); break
            default: return -1
            }
            return view.currentIndex
        }

        RowKeys {
            id: keys
            selectionModel: root.selectionModel
            onChose: (row, modifiers) => {
                root.tileKeyed(row, modifiers)
                view.positionViewAtIndex(row, GridView.Contain)
            }
        }
        WheelScroll {
            view: view
            enabled: root.wheelFix
        }

        Connections {
            target: root.selectionModel
            function onSelectionChanged() {
                view.selectionChanges++
            }
        }
        FontMetrics {    // the two lines as `Tile`'s Text draws them, Houdini's font, the name bold
            id: nameFont
            font.family: Typography.defaultFamily
            font.pixelSize: Typography.medium
            font.bold: true
        }
        FontMetrics {
            id: subtitleFont
            font.family: Typography.defaultFamily
            font.pixelSize: Typography.medium
        }
        Item {    // the grid's empty space under and beside the tiles: a click there clears, as in Qt's views
            parent: view.contentItem    // among the tiles, so the grid's flick takes its clicks as theirs
            z: -1
            width: view.width
            height: Math.max(view.height, view.contentHeight)
            TapHandler {
                gesturePolicy: TapHandler.WithinBounds
                onTapped: view.clickedOn(-1, point.modifiers)
            }
        }

        // a tap handler gives no focus (Qt gives it only to an item taking the press itself): so here
        function clickedOn(row, modifiers) {
            view.forceActiveFocus(Qt.MouseFocusReason)
            root.tileClicked(row, modifiers)
        }

        delegate: Tile {
            id: tile
            width: view.cellWidth
            height: view.cellHeight
            drawn: root.drawn
            badges: root.badges
            marks: root.marks
            nameHeight: view.nameHeight
            subtitleHeight: view.subtitleHeight
            selected: view.selectionChanges >= 0 && root.selectionModel !== null
                      && root.selectionModel.isSelected(view.model.index(index, 0))
            onClicked: modifiers => view.clickedOn(index, modifiers)
            onDoubleClicked: root.tileDoubleClicked(index)
            onHeldChanged: if (held) view.holder = tile; else if (view.holder === tile) view.holder = null
            onDragged: modifiers => root.tileDragged(index, modifiers)
            onBadgeClicked: name => {
                view.forceActiveFocus(Qt.MouseFocusReason)
                root.badgeClicked(index, name)
            }
        }
    }
}
