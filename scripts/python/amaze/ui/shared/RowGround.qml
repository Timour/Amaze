// A row's ground as Houdini's tree draws it, across the whole row; red where the row failed.
import QtQuick
import houdini.ui

Item {
    id: root

    property bool highlighted: false
    property bool failed: false    // what the row names cannot be reached: its highlight is red
    property bool alternate: false
    property color ground: Theme.viewSurface    // Houdini's list rows, as its widget trees paint them
    property color groundAlt: Theme.viewSurfaceAlt
    readonly property color fg: (    // the text on it, in the pair Houdini's theme gives each ground
        !root.highlighted ? Theme.fieldFg
            : root.failed ? Theme.errorSurfaceFg : Theme.highlightSurfaceFg
    )

    implicitHeight: 20
    Rectangle {    // square stripes, as Houdini's stock tree draws them; its QML tree rounds them
        anchors.fill: parent
        color: (
            !root.highlighted ? (root.alternate ? root.groundAlt : root.ground)
                : root.failed ? Theme.errorSurface : Theme.highlightSurface
        )
    }
}
