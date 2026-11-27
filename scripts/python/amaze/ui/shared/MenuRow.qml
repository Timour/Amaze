// The one menu row: Houdini's MenuItem with its height while its menu is closed too.
import QtQuick
import houdini.pluto
import houdini.ui

MenuItem {
    id: row
    // Houdini's row is 0 high until its menu shows ▸r/qml-menu-placed-before-layout
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             contentItem.implicitHeight + topPadding + bottomPadding,
                             implicitIndicatorHeight + topPadding + bottomPadding)
    symbolColor: enabled ? textColor : Theme.dimFg

    contentItem: SymbolLabel {    // pluto's label, but a greyed row's glyph keeps the text's colour on hover
        leftPadding: row.textPadding
        rightPadding: row.subMenu && row.arrow ? row.arrow.width + row.spacing : 0
        spacing: row.spacing
        alignment: Qt.AlignLeft
        icon: row.icon
        text: row.text
        symbol: row.symbol
        symbolColor: row.enabled && (row.down || row.hovered) ? Theme.highlightFg : row.symbolColor
        font: row.font
        color: row.effectiveTextColor
        highlighted: row.down || row.hovered
    }
}
