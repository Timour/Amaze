"""StatePictures: a QML image provider whose pictures its state gives on the main thread."""

from PySide6 import QtCore, QtGui, QtQml, QtQuick


class StatePictures(QtQuick.QQuickImageProvider):
    """A picture the state gives on the main thread, kept nowhere; `picture(key)` finds it."""

    def __init__(self, state) -> None:
        super().__init__(QtQml.QQmlImageProviderBase.ImageType.Image)
        self._state = state

    def picture(self, key: str):
        """The QImage for `key`, or None."""
        return None

    def requestImage(self, key: str, size: QtCore.QSize, requested: QtCore.QSize) -> QtGui.QImage:
        try:
            image = self.picture(key)
        except (RuntimeError, ValueError):    # the pane closed, or a url not made by this pane
            image = None
        if image is None or image.isNull():    # a null image is an error in the QML log: a clear dot instead
            image = QtGui.QImage(1, 1, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtCore.Qt.GlobalColor.transparent)
        elif requested.isValid() and (image.width() > requested.width() or image.height() > requested.height()):
            image = image.scaled(requested, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                 QtCore.Qt.TransformationMode.SmoothTransformation)
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image
