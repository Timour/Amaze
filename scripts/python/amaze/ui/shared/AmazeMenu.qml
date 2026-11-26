// The one menu: Houdini's Menu, filled from the menu engine's rows, picked once, then destroyed.
import QtQuick
import houdini.pluto
import houdini.ui

Menu {
    id: root

    enter: null    // whole on its first frame: the grow-and-fade shows nothing for 250 ms
    exit: null    // a menu still fading out keeps the release of the click that closed it
    delegate: entry    // a submenu's row too has its height while the menu is closed

    property string chosen: ""    // the picked row's key, handed on only once the menu has closed
    signal picked(string key)
    signal finished()    // every close, after `picked`, a row picked or not

    function show(rows) {    // fills the menu and opens it at the cursor
        root.fill(root, rows)
        root.popup()
    }

    function showAt(rows, at) {    // fills the menu and opens it at screen point `at`
        root.fill(root, rows)
        root.popup(root.parent.mapFromGlobal(at.x, at.y))
    }

    function showUnder(rows, item) {    // fills the menu and opens it below `item`, left edges lined up
        root.fill(root, rows)
        root.popup(item, 0, item.height)
    }

    function layOut(menu) {    // pluto's ListView takes the rows now: Qt places the menu at its full height
        menu.contentItem.children[0].forceLayout()
    }

    function rowSymbol(row) {    // the row's Phosphor glyph; a colour with none is Houdini's square in it
        if (row.glyph)
            return PhosphorGlyphs[row.glyph]
        return row.chip ? PhosphorGlyphs.square : ""
    }

    function fill(menu, rows) {    // rows as `pane.menus.Menu` gives them, a submenu's in `rows`
        for (const row of rows) {
            if (row.separator) {
                menu.addItem(divider.createObject(menu.contentItem))
            } else if (row.rows !== undefined) {
                const sub = submenu.createObject(menu, { title: row.text })
                root.fill(sub, row.rows)
                menu.addMenu(sub)
                const opener = menu.itemAt(menu.count - 1)    // the row Houdini's Menu made for it
                opener.enabled = row.enabled
                opener.symbol = root.rowSymbol(row)
                if (!row.enabled)    // Houdini's row dims its text but not its glyph
                    opener.symbolColor = Theme.dimFg
            } else {
                // `checked` alone draws the mark: Houdini's MenuItem cannot set checkable in a window menu
                // owned by the menu, not in it yet: our pick is wired before the menu's own close
                const item = entry.createObject(menu, { text: row.text, enabled: row.enabled,
                                                        checked: row.checked === true,
                                                        symbol: root.rowSymbol(row) })
                if (row.chip)
                    item.symbolColor = row.chip
                if (row.iconFile)    // Houdini's own icon system draws our SVG ▸r/pluto-menu-runtime
                    item.icon.source = row.iconFile
                const key = row.key
                item.triggered.connect(() => root.chosen = key)    // before the menu closes it
                menu.addItem(item)
            }
        }
        root.layOut(menu)
    }

    onClosed: {    // the row runs after the menu is gone, so a window it opens is not under a closing menu
        if (root.chosen !== "")
            root.picked(root.chosen)
        root.finished()
        root.destroy()
    }

    Component {
        id: entry
        MenuItem {    // pluto's height, kept while the menu is closed ▸r/qml-menu-placed-before-layout
            implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                                     contentItem.implicitHeight + topPadding + bottomPadding,
                                     implicitIndicatorHeight + topPadding + bottomPadding)
            symbolColor: enabled ? textColor : Theme.dimFg    // Houdini's row dims its text but not its glyph
        }
    }
    Component {
        id: divider
        MenuSeparator {}
    }
    Component {
        id: submenu
        Menu {
            enter: null    // whole on its first frame, as its menu
            exit: null    // closed by the same press as its menu, so gone before the release too
            delegate: entry    // its own submenus' rows, as its menu's
        }
    }
}
