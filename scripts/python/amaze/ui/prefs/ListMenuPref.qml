// A MenuPref whose options change while its page is shown. Its menu is sized by its rows, because
// Houdini's menu takes the height its list measured, which is 0 after a change while closed.
import QtQuick
import houdini.pluto
import houdini.prefs

MenuPref {
    id: root

    // one of Houdini's own menu rows, never drawn, for the height each row of the menu takes
    readonly property Item menuRow: MenuItem {
        text: " "
    }

    popup.implicitHeight: root.options.length * root.menuRow.implicitHeight * popup._scale
}
