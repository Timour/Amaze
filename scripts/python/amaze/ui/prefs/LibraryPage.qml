// The Library page: its rows in three Groups of Houdini's own pieces, as the P01 frame draws them.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Libraries"

        // A list with its buttons under it, as Houdini's theme menus hold theirs
        ListMenuPref {
            label: "Active Library"
            pref: "library"
            options: SharedState.libraryOptions

            Row {
                topPadding: 4
                bottomPadding: 4
                spacing: 8

                Button {
                    text: "Add"
                    onClicked: SharedState.addLibrary()

                    TipArea {
                        anchors.fill: parent
                        tipID: "add_library"
                    }
                }
                Button {
                    text: "Manage"
                    onClicked: manageDialog.open()

                    TipArea {
                        anchors.fill: parent
                        tipID: "manage_libraries"
                    }
                }
                Button {
                    text: "Reload"
                    enabled: SharedState.libraryOpen
                    onClicked: SharedState.reloadLibrary()

                    TipArea {
                        anchors.fill: parent
                        tipID: "reload_library"
                    }
                }
                Button {
                    text: "Show Folder"
                    enabled: SharedState.libraryOpen
                    onClicked: SharedState.showLibraryFolder()

                    TipArea {
                        anchors.fill: parent
                        tipID: "show_library_folder"
                    }
                }
            }
        }
        LabeledPref {
            label: "Check Database"
            tipID: "check_library"

            RowLayout {
                width: parent.width
                height: SharedState.rowHeight
                spacing: 8

                Button {
                    text: SharedState.checkLabel
                    danger: SharedState.checkFixable
                    enabled: SharedState.libraryOpen
                    Layout.preferredHeight: SharedState.rowHeight
                    onClicked: SharedState.checkOrRepair()

                    TipArea {
                        anchors.fill: parent
                        tipID: "check_library"
                    }
                }
                Text {
                    text: SharedState.libraryFormat
                    color: Theme.dimFg
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                }
                // One light for the whole check; what it found is its tip
                Rectangle {
                    width: 9
                    height: 9
                    radius: width / 2
                    color: SharedState.checkLight
                    Layout.alignment: Qt.AlignVCenter

                    TipArea {
                        anchors.fill: parent
                        text: SharedState.checkTip
                    }
                }
            }
        }
    }
    Group {
        text: "Users"

        ListMenuPref {
            label: "Active User"
            pref: "library_user"
            options: SharedState.userOptions

            Help {
                text: "Pick or create a user"
                shown: !SharedState.userPicked
            }
            Row {
                topPadding: 4
                bottomPadding: 4
                spacing: 8

                Button {
                    text: "Rename"
                    enabled: SharedState.userEditable
                    onClicked: SharedState.renameUser()

                    TipArea {
                        anchors.fill: parent
                        tipID: "rename_user"
                    }
                }
                Button {
                    text: "Delete"
                    enabled: SharedState.userEditable
                    onClicked: SharedState.deleteUser()

                    TipArea {
                        anchors.fill: parent
                        tipID: "delete_user"
                    }
                }
            }
        }
        TogglePref {
            label: "Enable Asset Versions"
            pref: "allow_overwrite"
        }
    }
    Group {
        text: "Paths"

        // The folder shown as TextPref shows its text, changed only by its buttons
        LabeledPref {
            label: "Cache Path"
            pref: "cache_dir"

            TextField {
                width: parent.width
                height: 20
                readOnly: true
                text: SharedState.cachePath
            }
            Row {
                topPadding: 4
                bottomPadding: 4
                spacing: 8

                Button {
                    text: "..."
                    onClicked: SharedState.changeCachePath()
                }
                Button {
                    text: "Default"
                    onClicked: SharedState.resetCachePath()

                    TipArea {
                        anchors.fill: parent
                        tipID: "default_cache"
                    }
                }
                Button {
                    text: "Delete"
                    onClicked: SharedState.deleteCache()

                    TipArea {
                        anchors.fill: parent
                        tipID: "delete_cache"
                    }
                }
            }
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
    }
    // What Apply does to the picked library, loose on the page as Houdini's APEX pages put theirs
    PrefMessage {
        text: SharedState.applyLine
        shown: SharedState.applyLine !== ""
        symbol: PhosphorGlyphs.warning
        symbolColor: Theme.yellow
    }

    // Both drawn in this window, blocking only it, as Houdini's OCIO page draws its Add Rule
    ManageLibrariesDialog {
        id: manageDialog
        anchors.centerIn: parent
    }
    UserNameDialog {
        id: nameDialog
        anchors.centerIn: parent
        onAccepted: SharedState.nameUser(nameDialog.name)
        onRejected: SharedState.prefsUpdated()    // the Active User row shows the user it showed before
    }

    // Python asks for the name dialog as Houdini's Node Search asks for its Save Query dialog
    Connections {
        target: SharedState

        function onUserNameRequested(title, name) {
            nameDialog.title = title
            nameDialog.name = name
            nameDialog.open()
        }
    }
}
