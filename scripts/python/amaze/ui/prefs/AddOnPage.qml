// The Add-On page: the installed add-ons' switches and the add-on updates, in Houdini's Groups.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Installed"

        Help {
            text: SharedState.addonsNone
            shown: SharedState.addonRows.length === 0
        }
        // One line for every switch, as Houdini's OpenCL group says a restart is due
        RequiresRestart {
            altered: SharedState.addonsAltered
            shown: SharedState.addonRows.length > 0
        }
        // A row per add-on group from the state; its picture where Houdini's Badges page puts an icon
        Repeater {
            model: SharedState.addonRows
            delegate: TogglePref {
                id: addonRow

                required property var modelData

                label: modelData.label
                pref: modelData.pref
                loadIcon: true
                iconComponent: Component {
                    Image {
                        source: addonRow.modelData.picture
                        width: addonRow.modelData.halved ? implicitWidth / 2 : 54
                        height: addonRow.modelData.halved ? implicitHeight / 2 : 54
                        sourceSize.width: addonRow.modelData.halved ? -1 : 54
                        sourceSize.height: addonRow.modelData.halved ? -1 : 54
                        fillMode: Image.PreserveAspectFit
                    }
                }

                Help {
                    text: addonRow.modelData.version + "<br>" + addonRow.modelData.author
                }
                Help {
                    text: addonRow.modelData.description

                    TipArea {
                        anchors.fill: parent
                        text: addonRow.modelData.tip
                    }
                }
            }
        }
    }
    Group {
        text: "Updates"

        TogglePref {
            label: "Add-On beta versions"
            pref: "addon_betas"
        }
        ButtonRow {
            Button {
                text: SharedState.addonsLabel
                enabled: !SharedState.addonsBusy
                height: SharedState.rowHeight
                onClicked: SharedState.pressAddons()

                TipArea {
                    anchors.fill: parent
                    tipID: SharedState.addonsOffered ? "addons_update" : "addons_check"
                }
            }
        }
        LabeledPref {
            shown: SharedState.addonsLine !== ""

            Help {
                text: SharedState.addonsLine
            }
        }
    }
}
