// The stripes below a view's last row, as Houdini's widget trees paint them; Qt's views stop there.
import QtQuick

Item {
    id: root

    required property TableView view    // a child of it, so the stripes go in its content
    property real rowHeight: 0    // a row's height as drawn; 0 for the ground's own
    readonly property real rowSize: view.rows > 0 ? view.contentHeight / view.rows
                                  : root.rowHeight > 0 ? root.rowHeight : ground.implicitHeight

    y: view.contentHeight
    z: -1

    RowGround {    // never shown: a view with no rows stripes at a ground's own height, as Qt's trees do
        id: ground
        visible: false
    }
    Repeater {
        model: Math.max(0, Math.ceil((root.view.height - root.view.contentHeight) / root.rowSize))
        RowGround {
            required property int index
            y: index * root.rowSize
            width: Math.max(root.view.width, root.view.contentWidth)
            height: root.rowSize
            alternate: root.view.alternatingRows && (root.view.rows + index) % 2 === 1
        }
    }
}
