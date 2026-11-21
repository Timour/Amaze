"""A picture file read straight into an image as wide as it is shown."""

from __future__ import annotations

import functools
import os

from PySide6 import QtCore, QtGui

from amaze.core import debug, workers
from amaze.helpers import hostos

QT_ENDINGS = (".jpg", ".jpeg", ".png", ".bmp", ".gif")    # Qt reads these far faster ▸r/image-preview
OIIO_ENDINGS = (".exr", ".hdr", ".tif", ".tiff", ".tga", ".tx")
ENDINGS = QT_ENDINGS + OIIO_ENDINGS    # .rat and .pic are not here: OpenImageIO has no reader for them
SCALE_FILTER = "box"    # ten times faster than the default filter on an 8192 px EXR ▸r/image-preview
MANY_CHANNELS = 4    # above this only the picture's own channels are read ▸r/image-preview
WHOLE = "whole"    # set on an image narrower than asked: the file has no more to read


def can_read(path: str) -> bool:
    """Whether `path` is a picture this module reads, by its ending."""
    return hostos.has_extension(os.path.basename(path), ENDINGS)


def _read_qt(path: str, width: int):
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)    # a camera's rotation flag is applied
    size = reader.size()    # as stored: a turned photo's width is its stored height ▸r/image-preview
    turned = reader.transformation() & QtGui.QImageIOHandler.Transformation.TransformationRotate90
    shown = size.height() if turned else size.width()
    if size.isValid() and shown > width:
        scale = width / shown
        reader.setScaledSize(QtCore.QSize(max(1, round(size.width() * scale)),
                                          max(1, round(size.height() * scale))))
    image = reader.read()
    return None if image.isNull() else image


def _read_oiio(path: str, width: int, cancelled):
    """The colour and alpha channels from the smallest MIP level wide enough, scaled to `width`."""
    import OpenImageIO as oiio

    source = oiio.ImageInput.open(path)
    if source is None:
        oiio.geterror()    # the reason is kept until it is read
        return None
    try:
        level, spec = 0, source.spec()
        while source.seek_subimage(0, level + 1):
            if source.spec().width < width:
                break
            level, spec = level + 1, source.spec()
        if spec.deep or spec.width < 1 or spec.height < 1 or cancelled():
            return None
        grey = spec.nchannels < 3    # one or two channels: the first is shown as grey
        channels = 1 if grey else 4 if spec.alpha_channel == 3 else 3    # alpha when it is the fourth
        linear = spec.format.basetype in (oiio.HALF, oiio.FLOAT, oiio.DOUBLE)    # scene values: view transform
        values = None
        if spec.nchannels > MANY_CHANNELS:    # a render with its passes: only the picture's channels are read
            kind = oiio.HALF if spec.format.basetype == oiio.HALF else oiio.FLOAT if linear else oiio.UINT8
            values = source.read_image(0, level, 0, channels, kind)
            if values is None:
                return None
    finally:
        source.close()
    if cancelled():
        return None
    if values is None:
        picture = oiio.ImageBuf(path, 0, level)    # this reads the pixels; a read() after it reads twice
        if picture.has_error or not picture.pixels_valid:
            return None
    else:
        picture = oiio.ImageBuf(oiio.ImageSpec(spec.width, spec.height, channels, kind))
        picture.set_pixels(oiio.ROI(0, spec.width, 0, spec.height), values)
        del values
    if cancelled():
        return None
    if spec.width > width:
        height = max(1, round(spec.height * width / spec.width))
        small = oiio.ImageBuf(oiio.ImageSpec(width, height, picture.nchannels,
                                             oiio.FLOAT if linear else oiio.UINT8))
        if not oiio.ImageBufAlgo.resize(small, picture, filtername=SCALE_FILTER) or cancelled():
            return None
        picture = small
    if picture.nchannels != channels:
        picture = oiio.ImageBufAlgo.channels(picture, tuple(range(channels)))
    if linear:
        shown = oiio.ImageBuf()    # the default display and view of the OCIO setup Houdini runs with
        if oiio.ImageBufAlgo.ociodisplay(shown, picture, "", "", ""):
            picture = shown
    pixels = picture.get_pixels(oiio.UINT8)
    if pixels is None or cancelled():
        return None
    height, wide = pixels.shape[0], pixels.shape[1]
    form = {1: QtGui.QImage.Format.Format_Grayscale8, 3: QtGui.QImage.Format.Format_RGB888,
            4: QtGui.QImage.Format.Format_RGBA8888_Premultiplied}[channels]    # ▸r/image-preview
    data = pixels.tobytes()
    return QtGui.QImage(data, wide, height, wide * channels, form).copy()    # its own memory, not `data`'s


def read(path: str, width: int, cancelled=None):
    """`path` as a QImage at most `width` px wide, or None when it cannot be read."""
    cancelled = cancelled or (lambda: False)
    width = max(1, int(width))
    try:
        image = None
        if hostos.has_extension(os.path.basename(path), QT_ENDINGS):
            image = _read_qt(path, width)
        if image is None and not cancelled():    # also a Qt picture over Qt's size limit
            image = _read_oiio(path, width, cancelled)
    except Exception as exc:                                  # noqa: BLE001 - the pane shows no picture
        debug.event("info", "a picture could not be read", path=path, error=str(exc))
        return None
    return None if cancelled() else image


class _ReadWorker(QtCore.QThread):
    """Runs one `read` off the UI thread and emits its image unless it was cancelled."""

    answered = QtCore.Signal(int, str, int, object)    # (token, path, width, image or None)

    def __init__(self, token: int, path: str, width: int) -> None:
        super().__init__()
        self.token, self.path, self.width = token, path, width
        self._canceled = False    # the stop flag workers.stop() sets, the name every worker uses

    def cancel(self) -> None:
        self._canceled = True

    def _stopped(self) -> bool:
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        image = read(self.path, self.width, self._stopped)
        if not self._stopped():
            self.answered.emit(self.token, self.path, self.width, image)


class _ReadEngine(QtCore.QObject):
    """Keeps every running read's thread until it ends; stops them on quit. ▸r/model-contracts"""

    def __init__(self) -> None:
        super().__init__()
        self._threads = []    # a running QThread must keep a reference until it ends ▸r/model-contracts

    def start(self, worker: _ReadWorker) -> None:
        worker.finished.connect(    # bound here, never sender(): ordering is per sender ▸r/model-contracts
            functools.partial(self._finished, worker))
        self._threads.append(worker)
        worker.start()

    def _finished(self, worker) -> None:
        self._threads = [t for t in self._threads if t is not worker and not workers.gone(t)]

    def shutdown(self) -> None:
        """Stop every read, THEN wait for each; safe twice and with nothing running."""
        workers.stop(self._threads, "preview")
        self._threads = []


engine = workers.install(__name__, _ReadEngine, QtCore.QCoreApplication.instance())


class Reader(QtCore.QObject):
    """Reads one picture at a time off the UI thread."""

    ready = QtCore.Signal(str, object)    # (path, image or None), on the UI thread

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._token = 0    # the newest ask's number; an answer with another number is dropped
        self._worker = None

    def ask(self, path: str, width: int) -> None:
        """Start reading `path` at `width`; a read still on its way for an earlier ask is dropped."""
        self.stop()
        worker = _ReadWorker(self._token, path, width)
        worker.answered.connect(self._answered)    # queued: the worker emits on its own thread
        self.destroyed.connect(worker.cancel)    # a deleted Reader stops its read
        self._worker = worker
        engine.start(worker)

    def stop(self) -> None:
        """Drop every read on its way; nothing is emitted afterwards."""
        self._token += 1
        worker, self._worker = self._worker, None
        if worker is not None:
            try:
                worker.cancel()
                self.destroyed.disconnect(worker.cancel)
            except (RuntimeError, TypeError):
                pass    # its C++ side is gone, or it was never connected

    def _answered(self, token: int, path: str, width: int, image) -> None:
        if token != self._token:
            return
        self._worker = None
        if image is not None and image.width() < width:
            image.setText(WHOLE, "1")
        self.ready.emit(path, image)
