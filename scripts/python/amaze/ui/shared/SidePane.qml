// A pane beside the grid in a SplitView, whose handle resizes it: its header band over its body.
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property alias band: band    // the header band: its icon, texts and figures
    property alias buttons: band.buttons    // the band's buttons
    default property alias content: body.data    // the body, filling the room under the band

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        HeaderBand {
            id: band
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
        }
        Item {
            id: body
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
        }
    }
}
