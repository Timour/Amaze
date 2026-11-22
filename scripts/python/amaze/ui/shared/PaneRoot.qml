// The root of an Amaze pane: Houdini's background and scale, as Houdini's own QML roots have them.
import QtQuick
import houdini.ui

Rectangle {
    id: root

    default property alias content: surface.data    // the pane's parts, laid out in design px

    anchors.fill: parent
    color: Theme.bg

    ScaledContent {
        id: surface
    }
}
