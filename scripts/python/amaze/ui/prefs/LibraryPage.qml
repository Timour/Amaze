// The Library page: the old Library tab's rows, in its order, in one Group of Houdini's own pieces.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import houdini.prefs

PrefsPage {
    Group {
        text: "Library"

        // A list with its buttons under it, as Houdini's theme menus hold theirs
        MenuPref {
            label: "Library"
            pref: "library"
            options: SharedState.libraryOptions

            Row {
                topPadding: 4
                bottomPadding: 4
                spacing: 8

                Button {
                    text: "Manage"
                    onClicked: manageDialog.open()

                    TipArea {
                        anchors.fill: parent
                        tipID: "manage_libraries"
                    }
                }
                Button {
                    text: "Add"
                    onClicked: SharedState.addLibrary()

                    TipArea {
                        anchors.fill: parent
                        tipID: "add_library"
                    }
                }
            }
        }
        ButtonRow {
            label: SharedState.libraryFormat

            Button {
                text: "Reload"
                enabled: SharedState.libraryOpen
                height: SharedState.rowHeight
                onClicked: SharedState.reloadLibrary()

                TipArea {
                    anchors.fill: parent
                    tipID: "reload_library"
                }
            }
            Button {
                text: "Show Folder"
                enabled: SharedState.libraryOpen
                height: SharedState.rowHeight
                onClicked: SharedState.showLibraryFolder()

                TipArea {
                    anchors.fill: parent
                    tipID: "show_library_folder"
                }
            }
        }
        // The Databases row's own headings over its lights; a light's column is 31 wide, 8 apart
        LabeledPref {
            RowLayout {
                width: parent.width
                spacing: 8

                Repeater {
                    model: SharedState.checkLights
                    delegate: Text {
                        required property var modelData

                        text: modelData.heading
                        color: Theme.dimFg
                        horizontalAlignment: Text.AlignRight
                        Layout.preferredWidth: 31
                    }
                }
                Item {
                    Layout.fillWidth: true
                }
            }
        }
        LabeledPref {
            label: "Databases"
            tipID: "check_library"

            RowLayout {
                width: parent.width
                height: SharedState.rowHeight
                spacing: 8

                Repeater {
                    model: SharedState.checkLights
                    delegate: Row {
                        required property var modelData

                        layoutDirection: Qt.RightToLeft    // the count ends under its heading
                        spacing: 5
                        Layout.preferredWidth: 31
                        Layout.alignment: Qt.AlignVCenter

                        Text {
                            text: modelData.count
                            color: Theme.dimFg
                        }
                        Rectangle {
                            width: 9
                            height: 9
                            radius: width / 2
                            color: modelData.fill
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
                Text {
                    text: SharedState.checkInfo
                    color: Theme.dimFg
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter

                    TipArea {
                        anchors.fill: parent
                        text: SharedState.checkTip
                    }
                }
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
            }
        }
        MenuPref {
            label: "User"
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
        TogglePref {
            label: "Versions"
            pref: "allow_overwrite"
        }
        // What Apply does to the picked library, as Houdini's pages put a warning in a group
        PrefMessage {
            text: SharedState.applyLine
            shown: SharedState.applyLine !== ""
            symbol: PhosphorGlyphs.warning
            symbolColor: Theme.yellow
        }
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
        onRejected: SharedState.prefsUpdated()    // the User row shows the user it showed before
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
