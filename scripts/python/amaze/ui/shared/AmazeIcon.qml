// An Amaze SVG icon drawn by Qt from its file in ui/; `color` fills its art where Amaze recolours it.
import QtQuick
import QtQuick.Controls.impl

IconImage {
    id: root

    property string file: ""    // the art's file name in ui/

    source: root.file ? Qt.resolvedUrl("../" + root.file) : ""
    sourceSize: Qt.size(root.width, root.height)    // Qt draws an SVG at this size times the screen's ratio
}
