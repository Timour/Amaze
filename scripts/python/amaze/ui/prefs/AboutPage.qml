// The About page: its text loose on the page, then the Updates and Developer Groups, as in P06.
import QtQuick
import houdini.pluto
import houdini.ui
import houdini.prefs
import "../shared"

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
    Item {    // GitHub's mark and the repository's address, as P06 draws them; a click opens the page
        readonly property var drawn: SharedState.repo
        width: parent.width
        height: drawn.row

        AmazeIcon {
            id: mark
            file: "icon_github.svg"
            x: parent.drawn.mark.x
            y: parent.drawn.mark.y
            width: parent.drawn.mark.w
            height: parent.drawn.mark.h
        }
        Text {
            x: mark.x + mark.width + parent.drawn.gap
            anchors.verticalCenter: mark.verticalCenter
            text: parent.drawn.address
            color: parent.drawn.text

            HoverHandler {
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                onTapped: SharedState.openRepo()
            }
        }
    }
    Group {
        text: "Updates"

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
        }
        // The version, then each check's or install's line, under its button as on the Add-On page
        LabeledPref {
            PrefMessage {    // its text under the button, its warning in the gap before it, as P06
                x: -(symbolSize + spacing)
                width: parent.width + symbolSize + spacing
                text: SharedState.versionLine
                symbol: SharedState.updateOffered ? PhosphorGlyphs.warning : ""    // only for an update to take
                symbolColor: Theme.yellow
            }
        }
    }
    Group {
        text: "Developer"

        TogglePref {
            label: "Debug Mode"
            pref: "debug_mode"
        }
        // The log's buttons and Report a Bug in the switch's column, as the P06 frame draws them
        LabeledPref {
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
                Button {
                    text: "Report a Bug..."
                    onClicked: SharedState.reportBug()

                    TipArea {
                        anchors.fill: parent
                        tipID: "report_bug"
                    }
                }
            }
        }
    }
}
