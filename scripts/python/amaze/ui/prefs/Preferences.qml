// Amaze Preferences: Houdini's own preferences root, with its page list, search and buttons.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefRoot {
    id: root

    // PrefRoot's Loader reads a relative url against Houdini's prefs folder: each url is resolved here
    initialPage: Qt.resolvedUrl("LibraryPage.qml")
    pageModel: [
        {text: "Library", icon: "BUTTONS_library", url: Qt.resolvedUrl("LibraryPage.qml")},
        {text: "Render", icon: "BUTTONS_render", url: Qt.resolvedUrl("RenderPage.qml")},
        {text: "UI", icon: "BUTTONS_ui", url: Qt.resolvedUrl("UiPage.qml")},
        {text: "Add-On", icon: "BUTTONS_plugin", url: Qt.resolvedUrl("AddOnPage.qml")},
        {text: "About", icon: "BUTTONS_info", url: Qt.resolvedUrl("AboutPage.qml")},
    ]
}
