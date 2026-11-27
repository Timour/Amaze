// Houdini's ScrollView with each bar shown only while its view has more than fits.
import QtQuick
import houdini.pluto

ScrollView {
    id: root

    function offered(bar) {    // the rule Houdini's ScrollBar.qml has for its handle at rest
        return bar.policy === ScrollBar.AlwaysOn || (bar.policy === ScrollBar.AsNeeded && bar.size < 1.0)
    }

    // Houdini's ScrollBar.qml stops hiding its handle after its first active state
    ScrollBar.vertical.visible: root.offered(root.ScrollBar.vertical)
    ScrollBar.horizontal.visible: root.offered(root.ScrollBar.horizontal)
}
