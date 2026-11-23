// The wheel as Houdini's Context Options list takes it: the event's pixels, else its step, at once.
import QtQuick

WheelHandler {
    id: handler

    required property Item view    // the view it scrolls, named as Houdini's list names its own

    function moved(position, delta, origin, content, shown) {    // one axis, kept inside the content
        return Math.min(Math.max(origin, origin + content - shown), Math.max(origin, position - delta))
    }

    acceptedDevices: PointerDevice.AllDevices    // Qt's default leaves out the trackpad
    onWheel: event => {    // a Mac mouse's pixels carry the Mac's speed-up; Qt's own wheel drops it
        const v = handler.view
        const dx = event.pixelDelta.x !== 0 ? event.pixelDelta.x : event.angleDelta.x
        const dy = event.pixelDelta.y !== 0 ? event.pixelDelta.y : event.angleDelta.y
        v.contentX = handler.moved(v.contentX, dx, v.originX, v.contentWidth, v.width)
        v.contentY = handler.moved(v.contentY, dy, v.originY, v.contentHeight, v.height)
    }
}
