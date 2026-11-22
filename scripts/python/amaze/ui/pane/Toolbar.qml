// The pane's toolbar: Houdini's own controls in frame B01's order, at B01's gaps.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

Item {
    id: root

    readonly property var drawn: SharedState.toolbar    // `amazetheme.drawn_toolbar`, by B01's names

    implicitHeight: drawn.height

    // Houdini's ToolButton with Amaze's art, its tip and its dimming as Houdini's Button has them
    component IconButton: ToolButton {
        id: button
        property string art: ""
        property string node: ""    // its name in B01, which gives the art's size
        property color artColor: "transparent"
        property string tip: ""
        flat: true
        padding: 0    // the art sits where B01 draws it inside the button, not inside Houdini's padding
        implicitWidth: root.drawn.button
        implicitHeight: root.drawn.button
        opacity: enabled ? 1.0 : Theme.disabledAlpha
        ToolTip.text: button.tip
        ToolTip.visible: button.hovered && button.tip !== ""
        ToolTip.delay: Config.toolTipDelay
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

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: root.drawn.edge
        anchors.bottomMargin: line.height
        spacing: 0

        IconButton {
            node: "btn_categories"
            art: "icon_categories.svg"
            tip: SharedState.tips.sidebar
            checked: SharedState.sidebarShown
            onClicked: SharedState.showSidebar(!SharedState.sidebarShown)
        }
        IconButton {    // the View and Filter menus go between, with the menus
            Layout.leftMargin: root.drawn.gap
            node: "btn_online"
            art: "icon_online.svg"
            artColor: SharedState.online ? SharedState.onlineColor : "transparent"
            tip: SharedState.tips.online
            checked: SharedState.online
            enabled: SharedState.onlinePossible
            onClicked: SharedState.setOnline(!SharedState.online)
        }
        IconButton {    // one button, its icon the current mode, as the widget panel's
            Layout.leftMargin: root.drawn.gap
            node: "cb_viewmode"
            art: SharedState.viewMode === "list" ? "list.svg" : "grid.svg"
            tip: SharedState.tips.viewMode
            onClicked: SharedState.setViewMode(SharedState.viewMode === "list" ? "grid" : "list")
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
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_prefs"
            art: "icon_library.svg"
            tip: SharedState.tips.prefs
            onClicked: SharedState.showPrefs()
        }
        IconButton {
            Layout.leftMargin: root.drawn.gap
            node: "btn_hip_capture"
            art: "icon_screenshot.svg"
            tip: SharedState.tips.capture
            enabled: SharedState.takesCapture
            onClicked: SharedState.capture()
        }
        Slider {
            readonly property var sizes: SharedState.tileSizes
            Layout.leftMargin: root.drawn.slider_gap
            Layout.fillWidth: true
            Layout.maximumWidth: root.drawn.slider_w
            from: sizes[0]
            to: sizes[sizes.length - 1]
            stepSize: SharedState.tileStepped ? sizes[1] - sizes[0] : 0
            snapMode: SharedState.tileStepped ? Slider.SnapAlways : Slider.NoSnap
            value: SharedState.tileSize
            enabled: SharedState.viewMode !== "list"    // a list row is one text line
            ToolTip.text: enabled ? SharedState.tips.tileSize : SharedState.tips.tileSizeList
            ToolTip.visible: hovered
            ToolTip.delay: Config.toolTipDelay
            onMoved: SharedState.setTileSize(Math.round(value))
        }
        Label {
            Layout.leftMargin: root.drawn.search_gap
            text: SharedState.words.search
        }
        SearchField {
            id: search
            Layout.leftMargin: root.drawn.label_gap
            Layout.fillWidth: true
            Layout.maximumWidth: root.drawn.field_w
            placeholderText: SharedState.searchHint
            ToolTip.text: SharedState.tips.search
            ToolTip.visible: hovered
            ToolTip.delay: Config.toolTipDelay
            onTextChanged: SharedState.typeSearch(text)

            Connections {
                target: SharedState
                function onSearchCleared() {
                    search.text = ""
                }
            }
        }
        Item {
            Layout.leftMargin: root.drawn.end_gap    // kept when the pane is narrow
            Layout.fillWidth: true
        }
    }

    Rectangle {
        id: line
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.field
    }
}
