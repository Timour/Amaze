// A tile as T01 and QML T20-T26 draw it, no tooltip: picture, name, subtitle, strip, buttons, marks.
import QtQuick
import houdini.pluto
import houdini.ui

Item {
    id: root

    required property int index
    required property var model    // the row's roles by name: display, tileSubtitle, picture, the buttons' and marks'
    property bool selected: false
    property var drawn: ({})    // `drawn_tile`: T01's spacing, the strip, the mark gap, the renderer icons
    property var badges: []    // `badge_rows`: the section's buttons on the picture
    property var marks: []    // `mark_rows`: the section's marks on the second line, right to left
    property real nameHeight: 15    // the two lines' heights, by the font, as the cell reserves them
    property real subtitleHeight: 15
    signal clicked(int modifiers)    // the user's click on the tile, away from a button
    signal doubleClicked()
    signal badgeClicked(string name)
    signal dragged(int modifiers)    // a press on the tile moved past the drag distance

    readonly property real side: width - 2 * root.drawn.pad    // the picture's side; the card is as wide
    readonly property real textTop: root.drawn.pad + root.side + root.drawn.img_text_gap
    readonly property real lineBottom: root.textTop + root.nameHeight + root.drawn.line_gap + root.subtitleHeight
    readonly property var picture: root.model.picture || ({})
    readonly property string subtitle: root.model.tileSubtitle || ""
    readonly property var lineMarks: {    // the marks shown on the second line, right to left, each with its x
        const shown = []
        const icon = (root.drawn.renderers || {})[root.model.rendererIcon || ""]    // Material's alone
        if (icon)
            shown.push(Object.assign({file: icon.art}, icon))
        for (const mark of root.marks) {
            const value = root.model[mark.role]
            if (mark.kindRole ? root.model[mark.kindRole] === mark.kind : value >= mark.least)    // houdini.ui's Number type hides JS Number
                shown.push(Object.assign({file: value ? mark.art : mark.off}, mark))
        }
        let left = root.drawn.pad + root.side
        for (let at = 0; at < shown.length; at++) {
            shown[at].x = at === 0 ? left - shown[at].inset - shown[at].width
                                   : left - root.drawn.markGap - shown[at].width
            left = shown[at].x
        }
        return shown
    }

    function place(edge, inset, size) {    // a button's offset in the picture: from its edge, or from the middle
        return edge === "end" ? root.side - size - inset : edge === "centre" ? (root.side - size) / 2 + inset : inset
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
            verticalAlignment: Image.AlignTop    // a wide picture sits at the top
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

    Repeater {    // the buttons, under the pointer; one that is on stays
        model: root.badges
        AmazeIcon {
            id: badge
            required property var modelData
            readonly property var value: root.model[modelData.role]
            readonly property bool on: modelData.on !== "" && !!value
            readonly property bool offered: !modelData.equals || value === modelData.equals    // Run: Python alone
            // the drawn size from the drawn picture up, in proportion below it, never under the least
            readonly property real fit: Math.max(Math.min(1, root.side / modelData.picture),
                                                 root.drawn.least / Math.min(modelData.width, modelData.height))
            visible: offered && (on || (modelData.button && hover.hovered))
            width: modelData.width * fit
            height: modelData.height * fit
            x: root.drawn.pad + root.place(modelData.edgeX, modelData.insetX, width)
            y: root.drawn.pad + root.place(modelData.edgeY, modelData.insetY, height)
            file: (modelData.button && press.pressed ? modelData.press
                   : on ? modelData.on : overBadge.hovered ? modelData.hover : modelData.art) + ".svg"

            HoverHandler {
                id: overBadge
                enabled: badge.modelData.button
            }
            TapHandler {
                id: press
                enabled: badge.modelData.button
                gesturePolicy: TapHandler.WithinBounds
                onTapped: root.badgeClicked(badge.modelData.name)
            }
        }
    }

    Repeater {    // the marks on the second line at their drawn size: the renderer, the open scene, a comment, versions
        model: root.lineMarks
        AmazeIcon {
            required property var modelData
            x: modelData.x
            y: root.lineBottom + modelData.below - height
            width: modelData.width
            height: modelData.height
            file: modelData.file + ".svg"
        }
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
    Text {    // the subtitle, eliding a text inset before the left-most mark
        x: root.drawn.pad + root.drawn.text_inset
        y: root.textTop + root.nameHeight + root.drawn.line_gap
        width: Math.max((root.lineMarks.length ? root.lineMarks[root.lineMarks.length - 1].x - root.drawn.text_inset
                                               : root.drawn.pad + root.side) - x, 1)
        height: root.subtitleHeight
        visible: root.subtitle !== ""
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.bold: root.selected
        color: root.selected ? Theme.highlightSurfaceFg : Theme.dimFg
        text: root.subtitle
    }
}
