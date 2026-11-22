// Manage Libraries: the Library list, most recent first; Remove from List takes libraries off it.
import QtQuick
import houdini.pluto
import houdini.ui

Dialog {
    id: root

    title: SharedState.manageLibrariesTitle
    implicitWidth: 420
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    standardButtons: Dialog.Cancel    // the Dialog gives its footer box its standard buttons

    // Qt's TableView and selection model as Houdini's Node Search and Geometry Spreadsheet use them;
    // the SelectionRectangle gives Ctrl-click, Shift-click and drag, a plain click makes a row current
    contentItem: Item {
        implicitHeight: 200

        TableView {
            id: tableView
            anchors.fill: parent
            model: SharedState.libraryRows
            clip: true
            focus: true
            selectionModel: ItemSelectionModel {}
            selectionMode: TableView.ExtendedSelection
            selectionBehavior: TableView.SelectRows
            ScrollBar.vertical: ScrollBar {}
            columnWidthProvider: column => (
                column === 0 ? SharedState.libraryNameWidth
                    : tableView.width - SharedState.libraryNameWidth
            )
            onWidthChanged: forceLayout()
            delegate: Rectangle {
                id: cell

                required property int row
                required property bool selected
                required property string display
                required property bool dim
                required property bool isOpen
                // the whole row, selected or current, as Node Search draws its rows; never the
                // open library, which cannot be removed, as the OCIO table leaves its Default rule
                readonly property bool rowSelected: (
                    !isOpen && (selected || row === tableView.currentRow)
                )

                implicitHeight: 20
                color: (
                    rowSelected ? Theme.highlightSurface
                        : (row % 2 ? Theme.fieldAlt : Theme.field)
                )

                Text {
                    anchors.fill: parent
                    text: cell.display
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideMiddle
                    leftPadding: 4
                    rightPadding: 4
                    color: (
                        cell.rowSelected ? Theme.highlightSurfaceFg
                            : (cell.dim ? Theme.dimFg : Theme.fieldFg)
                    )
                }
            }
        }
        SelectionRectangle {
            target: tableView
            selectionMode: SelectionRectangle.Drag
            topLeftHandle: null
            bottomRightHandle: null
        }
    }

    // Cancel closes, the removals already made kept; Remove takes the rows drawn highlighted
    footer: DialogButtonBox {
        Button {
            text: SharedState.removeFromListLabel
            implicitHeight: 22
            enabled: (
                tableView.selectionModel.hasSelection
                || (tableView.itemAtCell(Qt.point(0, tableView.currentRow))?.rowSelected ?? false)
            )
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: SharedState.removeLibraries(
                tableView.selectionModel.currentIndex, tableView.selectionModel.selectedRows(0)
            )
        }
    }

    onAboutToShow: SharedState.listLibraries()
}
