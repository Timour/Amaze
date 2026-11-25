// The one drop-down list: Houdini's ComboBox, its menu as tall as its rows, which may change while closed.
import QtQuick
import houdini.pluto

ComboBox {
    id: root

    readonly property Item menuRow: MenuItem {    // one of Houdini's own menu rows, never drawn: a row's height
        text: " "
    }

    popup.implicitHeight: root.count * root.menuRow.implicitHeight * popup._scale    // ▸r/pluto-combobox-zero-height
}
