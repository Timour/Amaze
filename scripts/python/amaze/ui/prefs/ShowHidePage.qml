// The Show/Hide page: the old dialog's two sub-tabs as two Groups of Houdini's own switches.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Renderer"

        Repeater {
            model: SharedState.rendererSwitches
            delegate: TogglePref {
                required property var modelData

                label: modelData.label
                pref: modelData.pref
            }
        }
    }
    Group {
        text: "Sections"

        Repeater {
            model: SharedState.sectionSwitches
            delegate: TogglePref {
                required property var modelData

                label: modelData.label
                pref: modelData.pref
            }
        }
    }
}
