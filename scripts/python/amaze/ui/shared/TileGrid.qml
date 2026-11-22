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
    signal tileClicked(int row, int modifiers)    // the user's click; row -1 is the grid's empty space
    signal badgeClicked(int row, string name)

    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

    GridView {
        id: view

        property int selectionChanges: 0    // counted, so every tile reads its selected state again
        // each line in whole px, as QFontMetrics gives the widget tile its cell
        readonly property int nameHeight: Math.round(nameFont.ascent) + Math.round(nameFont.descent)
        readonly property int subtitleHeight: Math.round(subtitleFont.ascent) + Math.round(subtitleFont.descent)

        clip: true
        cacheBuffer: 0    // tiles, and their pictures, only while on screen
        keyNavigationEnabled: false    // the keys come with a later step
        cellWidth: root.tileSize + root.drawn.width_extra
        cellHeight: root.drawn.pad + cellWidth - 2 * root.drawn.pad + root.drawn.img_text_gap
                    + nameHeight + root.drawn.line_gap + subtitleHeight + root.drawn.bottom_pad

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
                onTapped: root.tileClicked(-1, point.modifiers)
            }
        }

        delegate: Tile {
            width: view.cellWidth
            height: view.cellHeight
            drawn: root.drawn
            badges: root.badges
            nameHeight: view.nameHeight
            subtitleHeight: view.subtitleHeight
            selected: view.selectionChanges >= 0 && root.selectionModel !== null
                      && root.selectionModel.isSelected(view.model.index(index, 0))
            onClicked: modifiers => root.tileClicked(index, modifiers)
            onBadgeClicked: name => root.badgeClicked(index, name)
        }
    }
}
