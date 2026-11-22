// A row's ground as Houdini's tree draws it, across the whole row; red where the row failed.
import QtQuick
import houdini.ui

Item {
    id: root

    property bool highlighted: false
    property bool failed: false    // what the row names cannot be reached: its highlight is red
    property bool alternate: false
    property color ground: Theme.field    // Houdini's TreeViewDelegate's own two row colours
    property color groundAlt: Theme.fieldAlt
    readonly property color fg: (    // the text on it, in the pair Houdini's theme gives each ground
        !root.highlighted ? Theme.fieldFg
            : root.failed ? Theme.errorSurfaceFg : Theme.highlightSurfaceFg
    )

    implicitHeight: 20
    Rectangle {    // the shape of Houdini's TreeViewDelegate background
        anchors.fill: parent
        anchors.rightMargin: 2
        radius: 4
        color: (
            !root.highlighted ? (root.alternate ? root.groundAlt : root.ground)
                : root.failed ? Theme.errorSurface : Theme.highlightSurface
        )
    }
}
