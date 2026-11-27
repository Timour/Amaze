// Amaze's preference drop-down: Houdini's MenuPref with `MenuBox` for its ComboBox.
import QtQuick
import houdini.prefs
import "../shared"

ChoiceBasePref {
    id: root

    property alias currentIndex: menu.currentIndex    // which ChoiceBasePref reads and sets

    MenuBox {
        id: menu

        model: root.options
        enabled: root.enabled
        width: root.contentWidth
        textRole: "text"
        valueRole: "value"
        currentIndex: root.findCurrentIndex(SharedState.getPref(root.pref, root.registry))
        onModelChanged: root.initialize()
        onActivated: {
            root.activated(currentIndex)
            if (root.pref)
                SharedState.setPref(root.pref, root.options[currentIndex].value, root.registry, root.autoApply)
        }
    }
}
