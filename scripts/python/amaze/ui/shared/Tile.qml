// A tile as T01 and T20 draw it, no tooltip: picture, name, subtitle, strip, renderer icon, badges.
import QtQuick
import houdini.pluto
import houdini.ui

Item {
    id: root

    required property int index
    required property var model    // the row's roles by name: display, tileSubtitle, picture and the badges'
    property bool selected: false
    property var drawn: ({})    // `drawn_tile`: T01's spacing, T20's strip, the badge rules, the renderer icons
    property var badges: []    // `badge_rows`: the section's badges in paint order
    property real nameHeight: 15    // the two lines' heights, by the font, as the cell reserves them
    property real subtitleHeight: 15
    signal clicked(int modifiers)    // the user's click on the tile, away from a badge that takes clicks
    signal doubleClicked()
    signal badgeClicked(string name)
    signal dragged(int modifiers)    // a press on the tile moved past the drag distance
    readonly property bool held: tap.pressed || drag.active    // pressed here: the grid holds its flicking

    readonly property real side: width - 2 * root.drawn.pad    // the picture's side; the card is as wide
    readonly property real textTop: root.drawn.pad + root.side + root.drawn.img_text_gap
    readonly property var picture: root.model.picture || ({})
    readonly property string subtitle: root.model.tileSubtitle || ""
    readonly property var mark: root.drawn.renderers[root.model.rendererIcon || ""]    // Material's alone
    readonly property real markX: root.drawn.pad + root.side - (root.mark ? root.mark.inset + root.mark.width : 0)

    function badgeShown(badge) {    // "on", "off" or "", as the widget tile works it out
        if (!badge.role)
            return "on"
        const value = root.model[badge.role]
        if (value)
            return badge.minimum ? (Number(value) >= badge.minimum ? "on" : "")
                                 : (!badge.equals || value === badge.equals ? "on" : "")
        return badge.off ? "off" : ""
    }
    function badgeArt(badge, shown, over, down) {    // each state's own art, its opacities as drawn
        if (shown === "off")
            return over && badge.offHover ? badge.offHover : badge.off
        if (badge.press && down)
            return badge.press
        return badge.hover && over ? badge.hover : badge.art
    }

    HoverHandler {
        id: hover
    }
    TapHandler {    // exclusive, so a badge's own click is not also a click on the tile
        id: tap
        gesturePolicy: TapHandler.WithinBounds
        onTapped: root.clicked(point.modifiers)
        onDoubleTapped: root.doubleClicked()
    }
    DragOut {    // past the drag distance it takes the press from the tap: no click
        id: drag
        onStarted: (at, modifiers) => root.dragged(modifiers)
    }

    Rectangle {    // a selected tile is Houdini's selection around its picture and under its text
        anchors.fill: parent
        visible: root.selected
        color: Theme.highlightSurface
    }
    Rectangle {    // the card under the picture and both lines
        x: root.drawn.pad
        y: root.drawn.pad
        width: root.side
        height: root.textTop + root.nameHeight + root.drawn.line_gap + root.subtitleHeight
                + root.drawn.bottom_pad - root.drawn.pad
        color: root.drawn.card    // T01's card, also the ground of a generic icon drawn without one
        Rectangle {    // the text's part of it is the selection's colour on a selected tile
            y: root.side
            width: parent.width
            height: parent.height - root.side
            visible: root.selected
            color: Theme.highlightSurface
        }
    }
    Rectangle {    // the category's colour under the picture, as T20 draws it; none on a selected tile
        x: root.drawn.pad
        y: root.drawn.pad + root.side
        width: root.side
        height: root.drawn.strip
        visible: !root.selected && !!root.model.categoryColor
        color: root.model.categoryColor || "transparent"
    }

    Item {    // the picture's square
        x: root.drawn.pad
        y: root.drawn.pad
        width: root.side
        height: root.side
        clip: root.picture.crop === true

        AmazeIcon {
            anchors.fill: parent
            visible: !!root.picture.art
            file: root.picture.art ? root.picture.art + ".svg" : ""
        }
        Image {    // a picture file, read in the background while the tile is on screen, then let go
            anchors.fill: parent
            asynchronous: true
            cache: false
            source: String(root.picture.url || "").startsWith("file:") ? root.picture.url : ""
            sourceSize: Qt.size(root.side, root.side)
            fillMode: root.picture.crop ? Image.PreserveAspectCrop : Image.PreserveAspectFit
            verticalAlignment: Image.AlignTop    // a wide picture sits at the top, as the widget tile draws it
        }
        Image {    // a painted picture: Python paints on the main thread, as on Qt's reader thread it deadlocks
            anchors.fill: parent
            asynchronous: false
            cache: false
            source: String(root.picture.url || "").startsWith("image:") ? root.picture.url : ""
            sourceSize: Qt.size(root.side, root.side)
            fillMode: Image.PreserveAspectFit
            verticalAlignment: Image.AlignTop
        }
    }

    Repeater {    // the badges, only under the pointer but for a heart that is on
        model: root.badges
        AmazeIcon {
            id: badge
            required property var modelData
            readonly property string shown: root.badgeShown(modelData)
            readonly property bool over: modelData.button && overBadge.hovered
            readonly property real edge: Math.max(root.drawn.least,
                                                  Math.min(Math.floor(root.side / root.drawn.part), modelData.side))
            visible: shown !== "" && (hover.hovered || (modelData.pinned && shown === "on"))
            x: root.drawn.pad + (modelData.endX ? root.side - edge - modelData.insetX : modelData.insetX)
            y: root.drawn.pad + (modelData.endY ? root.side - edge - modelData.insetY : modelData.insetY)
            width: edge
            height: edge
            file: root.badgeArt(modelData, shown, over, press.pressed) + ".svg"

            HoverHandler {
                id: overBadge
                enabled: badge.modelData.button
            }
            TapHandler {
                id: press
                enabled: badge.modelData.wired
                gesturePolicy: TapHandler.WithinBounds
                onTapped: root.badgeClicked(badge.modelData.name)
            }
        }
    }

    AmazeIcon {    // the renderer's icon at the subtitle's right end, as T24-T26 draw it
        visible: root.mark !== undefined
        x: root.markX
        y: root.textTop + root.nameHeight + root.drawn.line_gap + root.subtitleHeight
           + (root.mark ? root.mark.below : 0) - height
        width: root.mark ? root.mark.width : 0
        height: root.mark ? root.mark.height : 0
        file: root.mark ? root.model.rendererIcon + ".svg" : ""
    }
    Text {    // the name, bold; alone, it sits in the middle of the two lines' room
        x: root.drawn.pad + root.drawn.text_inset
        y: root.textTop + (root.subtitle ? 0 : (root.drawn.line_gap + root.subtitleHeight) / 2)
        width: root.side - root.drawn.text_inset
        height: root.nameHeight
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.bold: true
        color: root.selected ? Theme.highlightSurfaceFg : Theme.secondarySurfaceFg
        text: root.model.display || ""
    }
    Text {    // the subtitle, ending a text inset before the renderer icon
        x: root.drawn.pad + root.drawn.text_inset
        y: root.textTop + root.nameHeight + root.drawn.line_gap
        width: Math.max((root.mark ? root.markX - root.drawn.text_inset : root.drawn.pad + root.side) - x, 1)
        height: root.subtitleHeight
        visible: root.subtitle !== ""
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.bold: root.selected
        color: root.selected ? Theme.highlightSurfaceFg : Theme.dimFg
        text: root.subtitle
    }
}
