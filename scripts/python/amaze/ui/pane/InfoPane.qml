// The Info pane, as N02 draws it: the selection's header, an image file's picture, then its facts.
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import houdini.pluto
import houdini.ui
import "../shared"

SidePane {
    id: root

    readonly property var drawn: SharedState.info    // N02's figures and the info pane's colours

    color: Theme.viewSurface    // N02's page is its rows' own ground
    band.drawn: root.drawn.band
    band.color: root.drawn.ground
    band.icon: "icon_info.svg"
    band.iconColor: SharedState.infoDimmed ? root.drawn.dim_icon : root.drawn.color
    band.iconOpacity: SharedState.infoDimmed ? root.drawn.dim_icon_opacity : 1
    band.textOpacity: SharedState.infoDimmed ? root.drawn.dim_text_opacity : 1
    band.name: SharedState.infoName
    band.type: SharedState.infoType
    buttons: ToolButton {    // only an image file has a picture to hide
        visible: SharedState.infoPreviewOffered
        Layout.alignment: Qt.AlignTop    // at N02's own top, which centring rounds away
        Layout.topMargin: root.drawn.preview_button_top
        flat: true
        padding: 0
        implicitWidth: root.drawn.preview_button
        implicitHeight: root.drawn.preview_button
        background: Item {}    // the art alone, as N02 draws it
        contentItem: AmazeIcon {
            file: SharedState.infoPreviewShown ? "icon_preview_hide.svg" : "icon_preview_show.svg"
        }
        ToolTip.text: SharedState.infoPreviewShown ? SharedState.tips.hidePreview : SharedState.tips.showPreview
        ToolTip.visible: SharedState.tipsShown && hovered
        ToolTip.delay: Config.toolTipDelay
        onClicked: SharedState.togglePreview()
    }

    ScrollArea {    // the page scrolls as a whole: the picture, its line and the rows
        anchors.fill: parent

        Flickable {
            id: page

            readonly property real screenWidth: page.width * SharedState.uiScale * Screen.devicePixelRatio

            interactive: false    // no drag scrolling, as Houdini's lists
            contentWidth: width
            contentHeight: picture.height + line.height + table.height
            onScreenWidthChanged: if (page.width > 0) SharedState.setPictureWidth(page.screenWidth)

            Connections {
                target: SharedState
                function onInfoAnother() {    // another selection starts at the top of the page
                    page.contentY = 0
                }
            }
            WheelScroll {
                view: page
            }

            Item {    // the picture whole and centred, never taller than it is at the page's width
                id: picture

                readonly property real whole: shown.implicitWidth > 0
                                              ? page.width * shown.implicitHeight / shown.implicitWidth : 0
                property real dragged: -1    // the height while its line is dragged, -1 otherwise
                readonly property real wanted: dragged >= 0 ? dragged : SharedState.infoPreviewHeight

                width: page.width
                height: SharedState.infoPicture !== "" ? Math.min(picture.wanted, picture.whole) : 0
                visible: height > 0

                Image {
                    id: shown
                    anchors.fill: parent
                    asynchronous: false    // the engine's picture, handed over on the main thread
                    cache: false    // no decoded picture is kept
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    source: SharedState.infoPicture
                }
            }
            Rectangle {    // the line under the picture; dragging it sets the picture area's height
                id: line
                y: picture.height
                width: page.width
                height: picture.visible ? root.drawn.drag_line : 0
                visible: picture.visible
                color: root.drawn.line

                MouseArea {
                    property real press: 0    // the pointer's y inside the line at the press
                    property bool moved: false

                    anchors.fill: parent
                    anchors.topMargin: -root.drawn.grab    // room to grab above and below the line
                    anchors.bottomMargin: -root.drawn.grab
                    cursorShape: Qt.SplitVCursor
                    onPressed: mouse => {
                        press = mouse.y - root.drawn.grab
                        moved = false
                    }
                    onPositionChanged: mouse => {
                        moved = true
                        const top = mapToItem(page.contentItem, 0, mouse.y).y - press
                        picture.dragged = Math.max(root.drawn.least, Math.min(top, picture.whole))
                    }
                    onReleased: {
                        if (moved)
                            SharedState.keepPreviewHeight(picture.dragged)
                        picture.dragged = -1
                    }
                    onCanceled: picture.dragged = -1
                }
            }
            RowsTable {
                id: table
                y: line.y + line.height
                width: page.width
                height: Math.max(table.contentHeight, page.height - y)    // the stripes reach the bottom
                headings: false
                scrolls: false
                model: SharedState.infoRows
                rowHeight: root.drawn.row
                drawn: SharedState.table
                columns: [{width: root.drawn.label_width, tick: false, inset: root.drawn.label_inset},
                          {width: Math.max(1, page.width - root.drawn.label_width), tick: false,
                           inset: root.drawn.value_inset, whole: true}]    // cut in the middle, tipped whole
            }
            Rectangle {    // N02's divider between the two columns, down the whole table
                x: root.drawn.label_width - root.drawn.divider / 2    // the drawn line's middle
                y: table.y
                width: root.drawn.divider
                height: table.height
                color: Theme.viewSurface    // the page's colour, so it shows on the bright rows only
            }
        }
    }
}
