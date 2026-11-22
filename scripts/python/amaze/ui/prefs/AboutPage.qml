// The About page: the old About tab's text loose on the page, then its buttons in Groups.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    // Loose on the page, above its groups, as Houdini's pages put a message before theirs
    Image {
        source: "image://amazelogo/logo"    // the wordmark trimmed to its pixels, by Amaze's provider
        width: parent.width
        height: SharedState.logoHeight
        sourceSize.height: height * Screen.devicePixelRatio
        fillMode: Image.PreserveAspectFit
        horizontalAlignment: Image.AlignLeft
    }
    Help {
        text: SharedState.aboutText + SharedState.creditsText
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
        text: "Developer"

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
}
