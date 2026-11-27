// A code field as Houdini's parameter pane draws one: its monospace text, its colours for the
// language, and the line numbers at the left, right-aligned and dim, a thin line beside them.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.ui.syntax

Item {
    id: root

    property alias text: area.text
    property string language: ""    // Houdini's highlighter for it, "" for none
    property color ground: Theme.field

    Rectangle {
        anchors.fill: parent
        color: root.ground
        border.width: area.activeFocus ? 1 : 0
        border.color: Qt.alpha(Theme.highlight, 0.5)
    }
    ScrollArea {
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        TextArea {
            id: area
            textFormat: TextEdit.PlainText
            font.family: Typography.monospaceFamily
            font.pixelSize: Typography.medium
            leftPadding: 6 + numbers.width
            rightPadding: 4
            topPadding: 2
            bottomPadding: 2
            wrapMode: TextEdit.Wrap

            Item {    // in the text area, so the numbers scroll with their lines
                id: numbers
                readonly property color ink: Qt.alpha(Theme.fg, 0.2)
                width: Math.ceil(digits.advanceWidth) + 8
                height: lines.height

                Column {
                    id: lines
                    width: parent.width
                    topPadding: area.topPadding
                    Repeater {
                        model: blocks.blockCount
                        Text {
                            required property int index
                            x: 4
                            width: numbers.width - 8
                            height: blocks.blockHeight(index)    // a wrapped line's number stands at its first row
                            text: index + 1
                            font: area.font
                            color: numbers.ink
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignTop
                        }
                    }
                }
                Rectangle {
                    x: numbers.width
                    width: 1
                    height: lines.height
                    color: numbers.ink
                }
                TextMetrics {
                    id: digits
                    font: area.font
                    text: blocks.blockCount
                }
                BlockStats {
                    id: blocks
                    document: area.textDocument
                }
            }
            SyntaxHighlight {
                document: area.textDocument
                language: root.language
            }
        }
    }
}
