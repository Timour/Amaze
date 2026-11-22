// The About page: the old About tab's text and buttons, in Groups of Houdini's own pieces.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Amaze"

        // The wordmark as Houdini's start window shows its own: the SVG in an Image
        Image {
            source: Qt.resolvedUrl("../logo.svg")
            height: 34
            sourceSize.height: height
            fillMode: Image.PreserveAspectFit
        }
        Help {
            text: "v" + SharedState.appVersion
        }
        Help {
            text: SharedState.aboutText
        }
    }
    Group {
        text: "Modules and libraries from other projects"

        Help {
            text: SharedState.creditsText
        }
    }
    Group {
        text: "Version"

        LabeledPref {
            Help {
                text: SharedState.versionLine
            }
        }
        ButtonRow {
            Button {
                text: SharedState.updateLabel
                enabled: !SharedState.updateBusy
                danger: SharedState.updateWarns
                height: SharedState.rowHeight
                onClicked: SharedState.pressUpdate()

                // A tip on a button, as Houdini's theme editor puts one on its switch
                TipArea {
                    anchors.fill: parent
                    tipID: SharedState.updateOffered ? "install_update" : "check_for_updates"
                }
            }
            Button {
                text: "Report a Bug..."
                height: SharedState.rowHeight
                onClicked: SharedState.reportBug()

                TipArea {
                    anchors.fill: parent
                    tipID: "report_bug"
                }
            }
            Button {
                text: "Convert pre-1.40"
                height: SharedState.rowHeight
                onClicked: SharedState.convertOldLibrary()
            }
        }
    }
    Group {
        text: "Debug"

        // Its buttons under the switch, as Houdini's UI Scale row holds its buttons
        TogglePref {
            label: "Debug Mode"
            pref: "debug_mode"

            Row {
                topPadding: 4
                bottomPadding: 4
                spacing: 8

                Button {
                    text: "Open Log"
                    onClicked: SharedState.openLog()

                    TipArea {
                        anchors.fill: parent
                        tipID: "open_log"
                    }
                }
                Button {
                    text: "Save Log..."
                    onClicked: SharedState.saveLog()

                    TipArea {
                        anchors.fill: parent
                        tipID: "save_log"
                    }
                }
                Button {
                    text: "Clear Log"
                    onClicked: SharedState.clearLog()

                    TipArea {
                        anchors.fill: parent
                        tipID: "clear_log"
                    }
                }
            }
        }
    }
    Group {
        text: "Add-Ons"

        TogglePref {
            label: "Add-On beta versions"
            pref: "addon_betas"
        }
    }
}
