// The UI page: Houdini's own rows in Groups; `pref` names the Amaze setting each one sets.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Categories"

        TogglePref {
            label: "Show Counts on Categories"
            pref: "sidebar_counts"
        }
        TogglePref {
            label: "Hide Empty Categories"
            pref: "hide_empty_categories"
        }
    }
    Group {
        text: "Grid"

        TogglePref {
            label: "Step Size"
            pref: "step_size"
        }
        ListMenuPref {
            label: "Custom Icons Line Width"
            pref: "icon_line_weight"
            options: [
                {text: "Thin", value: "template"},
                {text: "Regular (Feather)", value: "feather"},
            ]
        }
    }
    Group {
        text: "File Tab"

        TogglePref {
            label: "Render RAT Files"
            pref: "render_rat_files"
        }
        // On is `system_file_icons` off: the switch shows the stored setting the other way round
        TogglePref {
            label: "Show Generic File Icons"
            pref: "system_file_icons"
        }
    }
    Group {
        text: "Renderer"

        // A row per renderer from the state, as Houdini's Badges page lists its rows
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
