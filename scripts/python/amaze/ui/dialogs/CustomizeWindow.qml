// Customize: a tile's name, category and tags, the picture it shows, and a custom icon's parts.
import QtQuick
import QtQuick.Layouts
import houdini.pluto
import houdini.ui
import "../shared"

DialogRoot {
    id: root

    readonly property var drawn: SharedState.drawn    // `amazetheme.drawn_customize`: the frame's gaps and boxes

    fills: true    // the icons take the window's height, which the user sets
    okText: SharedState.words.accept    // Accept commits and closes; Apply commits and keeps the window
    applyText: SharedState.words.apply
    cancelText: ""    // the frame draws none
    buttonWidth: drawn.buttons[0]
    okWidth: drawn.buttons[1]
    buttonGap: drawn.pair_gap
    marginTop: drawn.top
    rowsGap: drawn.button_gap
    marginBottom: drawn.bottom
    answer: ({name: nameField.text, tags: tagsField.text, category: categoryBox.currentValue ?? ""})

    component FieldLabel: Text {    // a field's label, at the right of the frame's label column
        Layout.preferredWidth: Math.max(implicitWidth, root.drawn.label_width)
        horizontalAlignment: Text.AlignRight
        color: Theme.label
    }
    component Swatch: ColorChip {    // Houdini's colour chip as a button, as its Preferences' colour rows
        id: swatch

        property var box: [0, 0, 0, 0]    // where the frame draws it
        property string tip: ""
        signal picked()

        x: box[0]
        y: box[1]
        width: box[2]
        height: box[3]
        enabled: SharedState.custom
        opacity: enabled ? 1.0 : Theme.disabledAlpha
        ToolTip.text: swatch.tip
        ToolTip.visible: over.hovered && swatch.tip !== ""
        ToolTip.delay: Config.toolTipDelay

        TapHandler {
            onTapped: swatch.picked()
        }
        HoverHandler {
            id: over
        }
    }

    ColumnLayout {
        width: parent.width
        height: parent.height
        spacing: 0

        GridLayout {    // Name, Category and Tags; a row the selection has no field for is left out
            Layout.fillWidth: true
            columns: 2
            columnSpacing: root.drawn.label_gap
            rowSpacing: root.drawn.row_gap

            FieldLabel {
                text: SharedState.words.name
                visible: nameField.visible
            }
            TextField {
                id: nameField
                Layout.fillWidth: true
                visible: SharedState.question.hasName
                enabled: SharedState.question.nameEnabled    // off for several tiles
                text: SharedState.question.name
                ToolTip.text: SharedState.tips.name
                ToolTip.visible: hovered
                ToolTip.delay: Config.toolTipDelay
                onEntered: root.accept()
                onCanceled: root.reject()    // Esc in Houdini's field
            }
            FieldLabel {
                text: SharedState.words.category
                visible: categoryBox.visible
            }
            MenuBox {
                id: categoryBox
                Layout.fillWidth: true
                visible: SharedState.question.hasCategory
                model: SharedState.categories
                textRole: "text"
                valueRole: "value"
                currentIndex: SharedState.categoryRow
                ToolTip.text: SharedState.tips.category
                ToolTip.visible: hovered
                ToolTip.delay: Config.toolTipDelay
            }
            FieldLabel {
                text: SharedState.words.tags
                visible: tagsField.visible
            }
            TextField {
                id: tagsField
                Layout.fillWidth: true
                visible: SharedState.question.hasTags
                text: SharedState.question.tags
                ToolTip.text: SharedState.tips.tags
                ToolTip.visible: hovered
                ToolTip.delay: Config.toolTipDelay
                onEntered: root.accept()
                onCanceled: root.reject()
            }
        }
        Item {    // the picture, and beside it the Image menu and a custom icon's colours, where the frame draws each
            Layout.fillWidth: true
            Layout.topMargin: root.drawn.block_gap
            implicitHeight: root.drawn.block

            Image {
                x: root.drawn.preview[0]
                y: root.drawn.preview[1]
                width: root.drawn.preview[2]
                height: root.drawn.preview[3]
                asynchronous: false    // the engine's picture, handed over on the main thread
                cache: false    // no decoded picture is kept
                fillMode: Image.PreserveAspectFit
                smooth: true
                source: SharedState.preview
            }
            Text {
                x: root.drawn.face_label
                anchors.verticalCenter: faceBox.verticalCenter
                text: SharedState.words.image
                color: Theme.label
            }
            MenuBox {
                id: faceBox
                x: root.drawn.face[0]
                y: root.drawn.face[1]
                width: root.drawn.face[2]
                model: SharedState.faces
                textRole: "text"
                valueRole: "value"
                enabledRole: "enabled"    // Image is greyed for a tile that can have no picture
                currentIndex: SharedState.faceRow
                ToolTip.text: SharedState.tips.image
                ToolTip.visible: hovered
                ToolTip.delay: Config.toolTipDelay
                onActivated: SharedState.chooseFace(currentValue)
            }
            Switch {    // centred on the frame's switch, at Houdini's own size
                x: root.drawn.light[0]
                y: root.drawn.light[1] + Math.floor((root.drawn.light[3] - height) / 2)
                spacing: root.drawn.light_gap
                text: SharedState.words.light
                enabled: SharedState.custom
                checked: SharedState.light
                ToolTip.text: SharedState.tips.light
                ToolTip.visible: hovered
                ToolTip.delay: Config.toolTipDelay
                onToggled: SharedState.setLight(checked)
            }
            Swatch {    // the background as it is; a click opens Houdini's colour picker on it
                id: chip
                box: root.drawn.chip
                color: SharedState.background
                tip: SharedState.tips.colour
                onPicked: SharedState.pickColour()
            }
            Text {
                x: chip.x + chip.width + root.drawn.chip_gap
                anchors.verticalCenter: chip.verticalCenter
                text: SharedState.words.colour
                color: Theme.label
            }
            Repeater {
                model: SharedState.presets
                delegate: Swatch {
                    required property var modelData
                    required property int index

                    box: root.drawn.presets[index]
                    color: modelData.value
                    tip: modelData.text
                    onPicked: SharedState.setBackground(modelData.value)
                }
            }
        }
        SearchField {
            Layout.fillWidth: true
            Layout.topMargin: root.drawn.search_gap
            enabled: SharedState.custom
            placeholderText: SharedState.words.search
            onTextChanged: SharedState.search(text)
            onEntered: root.accept()
            onEscapePressed: root.reject()    // Esc in an empty box; in a filled one Houdini's field empties it
        }
        ScrollArea {    // the icons the search lists; only those on screen are made
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.topMargin: root.drawn.grid_gap
            enabled: SharedState.custom
            opacity: enabled ? 1.0 : Theme.disabledAlpha
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            GridView {
                id: icons

                clip: true
                interactive: false    // no drag scrolling, as Houdini's lists
                cacheBuffer: 0    // icons only while on screen
                cellWidth: root.drawn.cell + root.drawn.cell_gap
                cellHeight: cellWidth
                model: SharedState.icons

                WheelScroll {    // always: Qt's own wheel is off with its drag scrolling
                    view: icons
                }

                delegate: ToolButton {    // Houdini's tool button, checked on the icon chosen
                    id: cell

                    required property string modelData

                    width: root.drawn.cell
                    height: root.drawn.cell
                    flat: true
                    checked: cell.modelData === SharedState.icon
                    ToolTip.text: cell.modelData
                    ToolTip.visible: hovered
                    ToolTip.delay: Config.toolTipDelay
                    onClicked: SharedState.chooseIcon(cell.modelData)
                    contentItem: Item {
                        AmazeIcon {
                            anchors.centerIn: parent
                            width: root.drawn.cell_art
                            height: width
                            file: "feather/" + cell.modelData + ".svg"
                            color: cell.effectiveTextColor
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: (nameField.visible && nameField.enabled ? nameField
                            : categoryBox.visible ? categoryBox : faceBox).forceActiveFocus()    // the first live row
}
