// The one menu: Houdini's Menu, filled from the menu engine's rows, picked once, then destroyed.
import QtQuick
import houdini.pluto
import houdini.ui

Menu {
    id: root

    enter: null    // whole on its first frame: the grow-and-fade shows nothing for 250 ms
    exit: null    // a menu still fading out keeps the release of the click that closed it

    property string chosen: ""    // the picked row's key, handed on only once the menu has closed
    signal picked(string key)
    signal finished()    // every close, after `picked`, a row picked or not

    function show(rows) {    // fills the menu and opens it at the cursor
        root.fill(root, rows)
        root.popup()
    }

    function showUnder(rows, item) {    // fills the menu and opens it below `item`, left edges lined up
        root.fill(root, rows)
        root.popup(item, 0, item.height)
    }

    function fill(menu, rows) {    // rows as `pane.menus.Menu` gives them, a submenu's in `rows`
        for (const row of rows) {
            if (row.separator) {
                menu.addItem(divider.createObject(menu.contentItem))
            } else if (row.rows !== undefined) {
                const sub = submenu.createObject(menu, { title: row.text })
                root.fill(sub, row.rows)
                menu.addMenu(sub)
                menu.itemAt(menu.count - 1).enabled = row.enabled
            } else {
                // `checked` alone draws the mark: Houdini's MenuItem cannot set checkable in a window menu
                const item = entry.createObject(menu.contentItem, { text: row.text, enabled: row.enabled,
                                                                     checked: row.checked === true })
                if (row.chip) {    // a colour: Houdini's square glyph in it
                    item.symbol = PhosphorGlyphs.square
                    item.symbolColor = row.chip
                }    // a ui/ icon is not drawn: Houdini's row takes only its own icon names
                const key = row.key
                item.triggered.connect(() => root.chosen = key)
                menu.addItem(item)
            }
        }
    }

    onClosed: {    // the row runs after the menu is gone, so a window it opens is not under a closing menu
        if (root.chosen !== "")
            root.picked(root.chosen)
        root.finished()
        root.destroy()
    }

    Component {
        id: entry
        MenuItem {}
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
        }
    }
}
