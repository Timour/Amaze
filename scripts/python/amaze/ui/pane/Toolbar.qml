// The pane's toolbar: Houdini's own controls in frame B01's order, at B01's gaps.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

Item {
    id: root

    readonly property var drawn: SharedState.toolbar    // `amazetheme.drawn_toolbar`, by B01's names

    signal menuAsked(var rows, Item under)    // a menu button's rows, for the pane to open below it

    implicitHeight: drawn.height

    component IconButton: ToolbarButton {    // a toolbar menu, "view" or "filter", opens below its button
        id: button
        onMenuAsked: name => root.menuAsked(SharedState.toolbarMenu(name), button)
    }

    RowLayout {    // the whole row's height: B01 centres the buttons and the box in it
        anchors.fill: parent
        anchors.leftMargin: root.drawn.edge
        anchors.rightMargin: root.drawn.right_edge
        spacing: 0

        IconButton {
            node: "btn_categories"
            art: "icon_categories.svg"
            tip: SharedState.tips.sidebar
            checked: SharedState.sidebarShown
            onClicked: SharedState.showSidebar(!SharedState.sidebarShown)
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_menu_view"
            art: "icon_renderer.svg"
            tip: SharedState.tips.viewMenu
            opens: "view"
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_menu_filter"
            art: "icon_view.svg"
            tip: SharedState.filterTip
            enabled: SharedState.filterOffered
            opens: "filter"
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_online"
            art: "icon_online.svg"
            artColor: SharedState.online ? SharedState.onlineColor : "transparent"
            tip: SharedState.tips.online
            checked: SharedState.online
            enabled: SharedState.onlinePossible
            onClicked: SharedState.setOnline(!SharedState.online)
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_info"
            art: "icon_info.svg"
            artColor: SharedState.infoShown ? SharedState.info.color : "transparent"
            tip: SharedState.tips.info
            checked: SharedState.infoShown
            enabled: SharedState.takesInfo
            onClicked: SharedState.showInfo(!SharedState.infoShown)
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_notes"
            art: "icon_comments.svg"
            artColor: SharedState.commentsShown ? SharedState.comments.color : "transparent"
            tip: SharedState.tips.comments
            checked: SharedState.commentsShown
            enabled: SharedState.takesComments
            onClicked: SharedState.showComments(!SharedState.commentsShown)
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "cb_favsonly"
            art: SharedState.favouritesOnly ? "favourite_on.svg" : "favourite.svg"
            tip: SharedState.tips.favourites
            checked: SharedState.favouritesOnly
            enabled: SharedState.takesFavourites
            onClicked: SharedState.showFavouritesOnly(!SharedState.favouritesOnly)
        }
        ButtonStrip {    // list or grid: Houdini's two-button strip, the shown mode checked
            id: modes
            readonly property var names: ["list", "grid"]    // B01's segments, left to right
            Layout.leftMargin: root.drawn.gap
            implicitHeight: root.drawn.button
            model: [{ icon: "list.svg" }, { icon: "grid.svg" }]
            passive: true    // checked from the pane's view mode, never by the press itself
            currentIndex: names.indexOf(SharedState.viewMode)
            iconSize: root.drawn.icons.cb_viewmode
            minButtonWidth: root.drawn.segment
            horizontalPadding: (root.drawn.segment - iconSize) / 2
            spacing: root.drawn.segment_gap
            contentDelegate: Item {
                AmazeIcon {
                    anchors.centerIn: parent
                    file: iconName    // handed on by the strip's Loader, as its own delegate reads it
                    width: modes.iconSize
                    height: width
                }
            }
            onTapped: index => SharedState.setViewMode(names[index])
            ToolTip.text: SharedState.tips.viewMode
            ToolTip.visible: SharedState.tipsShown && hover.hovered
            ToolTip.delay: Config.toolTipDelay

            HoverHandler {
                id: hover
            }
        }
        Slider {    // Houdini's, with no tick marks on the toolbar
            readonly property var sizes: SharedState.tileSizes
            Layout.leftMargin: root.drawn.slider_gap
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: root.drawn.slider_top
            Layout.fillWidth: true
            Layout.maximumWidth: root.drawn.slider_w
            Layout.preferredHeight: root.drawn.slider_h
            from: sizes[0]
            to: sizes[sizes.length - 1]
            trackThickness: root.drawn.track
            handleSize: root.drawn.handle
            stepSize: SharedState.tileStepped ? sizes[1] - sizes[0] : 0
            snapMode: SharedState.tileStepped ? Slider.SnapAlways : Slider.NoSnap
            value: SharedState.tileSize
            enabled: SharedState.viewMode !== "list"    // a list row is one text line
            layer.enabled: !enabled    // Houdini dims it by opacity; flat, the groove no longer shows through
            ToolTip.text: enabled ? SharedState.tips.tileSize : SharedState.tips.tileSizeList
            ToolTip.visible: SharedState.tipsShown && hovered
            ToolTip.delay: Config.toolTipDelay
            onMoved: SharedState.setTileSize(Math.round(value))
        }
        Label {
            Layout.leftMargin: root.drawn.search_gap
            Layout.fillHeight: true
            Layout.preferredWidth: Math.max(implicitWidth, root.drawn.label_w)    // B01's box, or the word's
            leftPadding: root.drawn.label_inset
            verticalAlignment: Text.AlignVCenter
            text: SharedState.words.search
        }
        TextField {    // Houdini's field, square as B01 draws it, with Amaze's magnifier
            id: search
            Layout.leftMargin: root.drawn.label_gap
            Layout.fillWidth: true
            Layout.maximumWidth: root.drawn.field_w
            Layout.preferredHeight: root.drawn.field_h
            leftPadding: root.drawn.field_text
            rightPadding: clear.visible ? clear.width : padding
            placeholderText: SharedState.searchHint
            ToolTip.text: SharedState.tips.search
            ToolTip.visible: SharedState.tipsShown && hovered
            ToolTip.delay: Config.toolTipDelay
            onTextChanged: SharedState.typeSearch(text)
            Keys.onEscapePressed: {    // as Houdini's SearchField: Esc empties a filled box
                if (search.text)
                    search.text = ""
            }

            AmazeIcon {
                file: "icon_search.svg"
                width: root.drawn.search_icon
                height: width
                x: root.drawn.search_pad
                y: Math.floor((parent.height - height) / 2)
            }
            RoundButton {    // Houdini's SearchField's clear button
                id: clear
                visible: search.text !== ""
                width: 22
                height: parent.height
                anchors.right: parent.right
                symbol: PhosphorGlyphs.x
                symbolSize: 14
                flat: true
                onClicked: search.text = ""
            }
            Connections {
                target: SharedState
                function onSearchCleared() {
                    search.text = ""
                }
            }
        }
        Item {    // the room left, never less than end_gap; the right-end button follows it
            Layout.leftMargin: root.drawn.end_gap
            Layout.fillWidth: true
        }
        IconButton {
            node: "btn_prefs"
            art: "icon_library.svg"
            tip: SharedState.tips.prefs
            on: SharedState.prefsOpen
            onClicked: SharedState.showPrefs()
        }
    }

    Rectangle {    // B01's bottom border, over the row's last line
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.field
    }
}
