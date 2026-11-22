// The Render page: Houdini's own rows in Groups; `pref` names the Amaze setting each one sets.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Thumbnails"

        SliderPref {
            label: "Size in Pixels"
            pref: "rendersize"
            from: SharedState.ranges.rendersize[0]
            to: SharedState.ranges.rendersize[1]
            isInt: true
        }
        // A row per renderer from the state, as Houdini's Badges page lists its rows
        Repeater {
            model: SharedState.samplesRows
            delegate: SliderPref {
                required property var modelData

                label: modelData.label
                pref: modelData.pref
                from: SharedState.ranges[modelData.pref][0]
                to: SharedState.ranges[modelData.pref][1]
                isInt: true
                shown: SharedState.offeredRenderers.includes(modelData.key)
            }
        }
        SliderPref {
            label: "MB of RAM Cache"
            pref: "ram_cache_mb"
            from: SharedState.ranges.ram_cache_mb[0]
            to: SharedState.ranges.ram_cache_mb[1]
            isInt: true
        }
        MenuPref {
            label: "Geometry Style"
            pref: "geometry_shading_mode"
            options: [
                {text: "Hidden Line Ghost", value: "hiddenlineghost"},
                {text: "Smooth Wire Shaded", value: "smoothwireshaded"},
                {text: "Smooth Shaded", value: "smoothshaded"},
                {text: "Flat Wire Shaded", value: "flatwireshaded"},
                {text: "Flat Shaded", value: "flatshaded"},
                {text: "Wireframe", value: "wireframe"},
                {text: "Hidden Line Invisible", value: "hiddenlineinvisible"},
            ]
        }
        MenuPref {
            label: "Geometry Background"
            pref: "geometry_bg"
            options: [
                {text: "Black", value: "black"},
                {text: "White", value: "white"},
                {text: "Default (grey sky)", value: "default"},
            ]
        }
        TogglePref {
            label: "Render Thumbnails on Import"
            pref: "render_on_import"
        }
    }
    Group {
        text: "Image Generation"

        SliderPref {
            label: "Conversion Threads"
            pref: "texture_parallel_conversions"
            from: SharedState.ranges.texture_parallel_conversions[0]
            to: SharedState.ranges.texture_parallel_conversions[1]
            isInt: true
        }
    }
    Group {
        text: "Downloads"

        MenuPref {
            label: "Download Resolution"
            pref: "matx_resolution"
            options: [
                {text: "1k", value: "1k"},
                {text: "2k", value: "2k"},
                {text: "4k", value: "4k"},
                {text: "8k", value: "8k"},
            ]
        }
        SliderPref {
            label: "Parallel Downloads"
            pref: "matx_parallel_downloads"
            from: SharedState.ranges.matx_parallel_downloads[0]
            to: SharedState.ranges.matx_parallel_downloads[1]
            isInt: true
        }
    }
}
