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

    // Houdini's ToolButton with Amaze's art, its tip and its dimming as Houdini's Button has them
    component IconButton: ToolButton {
        id: button
        property string art: ""
        property string node: ""    // its name in B01, which gives the art's size
        property color artColor: "transparent"
        property string tip: ""
        property string opens: ""    // the toolbar menu a press opens below it: "view" or "filter"
        property QtObject menu: null    // that menu while it is open; Qt clears it when the menu goes
        property bool on: checked || menu !== null    // B01c's on state: a toggle on, a menu or window open
        // a menu's window takes its button's release: a menu button stays held ▸r/qml-menu-press
        readonly property bool held: down && opens === ""
        flat: true
        padding: 0    // the art sits where B01 draws it inside the button, not inside Houdini's padding
        implicitWidth: root.drawn.button
        implicitHeight: root.drawn.button
        opacity: enabled ? 1.0 : Theme.disabledAlpha
        layer.enabled: !enabled    // dimmed as one picture, or the chip would show through the art
        ToolTip.text: button.tip
        ToolTip.visible: button.hovered && button.tip !== ""
        ToolTip.delay: Config.toolTipDelay
        onPressed: if (button.opens !== "") root.menuAsked(SharedState.toolbarMenu(button.opens), button)
        background: Item {
            Rectangle {    // B01c's chip: its grey middle, Houdini's checked border and ring
                anchors.fill: parent
                visible: button.on || button.held
                radius: 4
                color: root.drawn.on.fill
                border.color: root.drawn.on.border
                border.width: 1
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: 3
                    color: "transparent"
                    border.color: root.drawn.on.ring
                    border.width: 1.5
                }
            }
            Rectangle {    // Houdini's tool-button hover (pluto parts.drawButtonPanel): white at 10%
                anchors.fill: parent
                visible: button.hovered && button.enabled && !button.on && !button.held
                radius: 4
                color: Qt.rgba(1, 1, 1, 0.1)
                border.color: Qt.rgba(1, 1, 1, 0.145)    // its pen over its fill, measured #4c4c4c at 1x
                border.width: 1
            }
        }
        contentItem: Item {
            AmazeIcon {
                readonly property var at: root.drawn.icon_at[button.node]
                file: button.art
                width: root.drawn.icons[button.node]
                height: width
                x: at ? at.x : Math.floor((parent.width - width) / 2)
                y: at ? at.y : Math.floor((parent.height - height) / 2)
                color: button.artColor
            }
        }
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
        // Info and Comments come here, at B01's btn_info and btn_notes, with their panes
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
            ToolTip.visible: hover.hovered
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
            ToolTip.visible: hovered
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
            ToolTip.visible: hovered
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
        Item {    // the room left, never less than end_gap; the right-end buttons follow it
            Layout.leftMargin: root.drawn.end_gap
            Layout.fillWidth: true
        }
        IconButton {
            node: "btn_hip_capture"
            art: "icon_screenshot.svg"
            tip: SharedState.tips.capture
            enabled: SharedState.takesCapture
            onClicked: SharedState.capture()
        }
        IconButton {
            Layout.leftMargin: root.drawn.right_gap
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
