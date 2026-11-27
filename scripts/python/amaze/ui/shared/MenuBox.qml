// The one drop-down list: Houdini's ComboBox, its menu as tall as its rows, which may change while closed.
import QtQuick
import houdini.pluto

ComboBox {
    id: root

    property string enabledRole: ""    // the role that greys a row where it is false; "" for no such role
    readonly property Item menuRow: MenuItem {    // one of Houdini's own menu rows, never drawn: a row's height
        text: " "
    }

    popup.implicitHeight: root.count * root.menuRow.implicitHeight * popup._scale    // ▸r/pluto-combobox-zero-height

    Binding {    // only a box that greys rows replaces Houdini's row, with Houdini's row that can be off
        target: root
        property: "delegate"
        when: root.enabledRole !== ""
        value: Component {
            MenuItem {    // as Houdini's ComboBox makes its row; a click on a greyed one picks nothing
                required property var model
                required property int index

                width: ListView.view.width
                text: model[root.textRole]
                enabled: !!model[root.enabledRole]
                font.weight: root.currentIndex === index ? Font.DemiBold : Font.Normal
                highlighted: root.highlightedIndex === index
                hoverEnabled: root.hoverEnabled
            }
        }
    }
}
