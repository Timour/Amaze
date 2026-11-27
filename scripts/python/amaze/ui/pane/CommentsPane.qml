// The Comments pane, as N01 draws it: the selection's header and add button, then its comment.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

SidePane {
    id: root

    readonly property var drawn: SharedState.comments    // N01's figures and the Comments pane's colours

    function moveTo(at) {    // the engine's answer: the text cursor's new place, -1 for none
        if (at < 0)
            return false
        edit.cursorPosition = at
        return true
    }
    function anchor() {    // the selection's other end from the cursor
        return edit.cursorPosition === edit.selectionStart ? edit.selectionEnd : edit.selectionStart
    }

    color: root.drawn.page
    band.drawn: root.drawn.band
    band.color: root.drawn.ground
    band.icon: "icon_comments.svg"
    band.iconColor: SharedState.commentsDimmed ? root.drawn.dim_icon : root.drawn.color
    band.iconOpacity: SharedState.commentsDimmed ? root.drawn.dim_icon_opacity : 1
    band.textOpacity: SharedState.commentsDimmed ? root.drawn.dim_text_opacity : 1
    band.name: SharedState.commentsName
    band.type: SharedState.commentsType
    buttons: ToolbarButton {    // the toolbar's own chip, shown while its menu is open
        id: add
        objectName: "commentsAdd"
        implicitWidth: root.drawn.chip
        implicitHeight: root.drawn.chip
        art: "icon_comments_add.svg"
        artSize: root.drawn.plus
        artAt: ({ x: root.drawn.plus_at, y: root.drawn.plus_at })
        artColor: SharedState.commentsDimmed ? root.drawn.dim_add : "transparent"
        hasMenu: true    // Houdini's own menu marker
        enabled: !SharedState.commentsDimmed
        opacity: 1    // N01B dims the art alone
        layer.enabled: false
        tip: SharedState.tips.addToComment
        opens: "add"
        onMenuAsked: {
            add.menu = adder.createObject(root)
            add.menu.showUnder(SharedState.commentAddRows(), add)
        }
    }

    Component {
        id: adder
        AmazeMenu {
            onPicked: key => {
                if (root.moveTo(SharedState.addToComment(key, edit.cursorPosition)))
                    edit.forceActiveFocus()
            }
        }
    }

    ScrollArea {
        anchors.fill: parent

        Flickable {
            id: page

            interactive: false    // no drag scrolling, as Houdini's lists
            contentWidth: width
            WheelScroll {
                view: page
            }

            TextArea.flickable: TextArea {    // Houdini's, which draws no field of its own
                id: edit
                objectName: "commentsEdit"
                textFormat: TextEdit.RichText    // the engine's blocks: margins, pictures, struck labels
                wrapMode: TextEdit.Wrap
                padding: root.drawn.doc_margin
                leftPadding: root.drawn.doc_margin    // pluto's is 2 more than its padding
                color: root.drawn.text
                enabled: !SharedState.commentsDimmed
                placeholderText: SharedState.commentsDimmed ? "" : SharedState.words.writeComment
                Component.onCompleted: SharedState.useCommentEditor(edit)
                Keys.onPressed: event => {    // the keys the engine owns; the rest are the editor's
                    if (event.matches(StandardKey.Paste))    // pasted text stays plain
                        event.accepted = root.moveTo(SharedState.pasteIntoComment(edit.cursorPosition,
                                                                                    root.anchor()))
                    else
                        event.accepted = root.moveTo(SharedState.commentKey(event.key, edit.cursorPosition,
                                                                             root.anchor()))
                }

                Repeater {    // each to-do's glyph, placed by the engine at its block
                    model: SharedState.commentGlyphs

                    Item {
                        required property var modelData

                        y: edit.topPadding + modelData.top
                        width: edit.leftPadding + modelData.right    // the zone left of the text, as the widget's
                        height: modelData.height

                        AmazeIcon {
                            x: edit.leftPadding + modelData.x
                            y: edit.topPadding + modelData.y - parent.y
                            width: modelData.side
                            height: width
                            file: modelData.done ? "feather/check-circle.svg" : "feather/circle.svg"
                            color: modelData.done ? root.drawn.done : root.drawn.open
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onPressed: SharedState.toggleComment(modelData.block)    // at the press, as the widget's
                        }
                    }
                }
            }
        }
    }
}
