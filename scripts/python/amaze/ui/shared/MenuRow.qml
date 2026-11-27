// The one menu row: Houdini's MenuItem with its height while its menu is closed too.
import QtQuick
import houdini.pluto
import houdini.ui

MenuItem {
    // Houdini's row is 0 high until its menu shows ▸r/qml-menu-placed-before-layout
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             contentItem.implicitHeight + topPadding + bottomPadding,
                             implicitIndicatorHeight + topPadding + bottomPadding)
    symbolColor: enabled ? textColor : Theme.dimFg    // Houdini's row dims its text but not its glyph
}
