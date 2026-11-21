// The Look page: each row is Houdini's own; `pref` names the Amaze setting it reads and writes.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    TogglePref {
        label: "Show Counts on Categories"
        pref: "sidebar_counts"
    }
    TogglePref {
        label: "Hide Empty Categories"
        pref: "hide_empty_categories"
    }
    TogglePref {
        label: "Step Size"
        pref: "step_size"
    }
    TogglePref {
        label: "Render RAT Files"
        pref: "render_rat_files"
    }
    TogglePref {
        label: "System File Icons"
        pref: "system_file_icons"
    }
    MenuPref {
        label: "Write Paths As"
        pref: "path_style"
        options: [
            {text: "$HOME", value: "home"},
            {text: "$JOB", value: "job"},
            {text: "$HIP", value: "hip"},
            {text: "Absolute", value: "absolute"},
        ]
    }
    MenuPref {
        label: "Tile Icon Line"
        pref: "icon_line_weight"
        options: [
            {text: "Thin", value: "template"},
            {text: "Regular (Feather)", value: "feather"},
        ]
    }
    SliderPref {
        label: "Scroll Speed (%)"
        pref: "scroll_speed"
        from: SharedState.scrollSpeedFrom
        to: SharedState.scrollSpeedTo
        isInt: true
    }
}
