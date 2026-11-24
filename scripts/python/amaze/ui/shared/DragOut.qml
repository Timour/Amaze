// A press that becomes a drag out of the pane past the platform's drag distance; the pane follows it.
import QtQuick

DragHandler {
    id: root

    signal started(point at, int modifiers)    // `at`: where the press was, in the parent's coordinates

    target: null    // nothing moves here: the pane's view follows the pointer, out of the pane too
    dragThreshold: Qt.styleHints.startDragDistance    // the distance Qt's widget views start a drag at
    onActiveChanged: if (active) root.started(centroid.pressPosition, centroid.modifiers)
}
