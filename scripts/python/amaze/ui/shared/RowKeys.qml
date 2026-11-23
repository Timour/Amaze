// Where an Amaze hotkey's move lands: the view's own arrows, the first and last row, a page of rows.
import QtQuick

QtObject {
    id: keys

    property var selectionModel: null    // the section's own, whose current row a move starts from
    readonly property int current: selectionModel !== null && selectionModel.currentIndex.valid
                                   ? selectionModel.currentIndex.row : -1
    signal chose(int row, int modifiers)    // the move landed on `row`; Shift when it extends

    // `page`: the rows a page moves; `arrow(name, from)`: the view's own move, -1 for one it does not take
    function step(name, extend, count, page, arrow) {
        const from = keys.current
        let row = -1
        switch (name) {
        case "home": row = 0; break
        case "end": row = count - 1; break
        case "page_up": row = Math.max(0, from - page); break
        case "page_down": row = Math.min(count - 1, Math.max(from, 0) + page); break
        default:
            row = arrow(name, Math.max(from, 0))
            if (row >= 0 && from < 0)
                row = 0    // no current row yet: an arrow lands on the first, as Qt's views do
        }
        if (row >= 0 && count > 0)
            keys.chose(row, extend ? Qt.ShiftModifier : Qt.NoModifier)
    }
}
