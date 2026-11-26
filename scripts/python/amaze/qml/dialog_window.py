"""DialogWindow: Amaze's separate dialog windows, made as Houdini makes its own windows."""

import math

from PySide6 import QtCore, QtQml

from amaze.core import debug
from hutil.qt.common import qmlviews    # Houdini's own QML windows' base ▸r/qml-widget-blackout

_open: dict = {}    # the one open window of each kind, by its class


class DialogState(qmlviews.SharedState):
    """What a dialog window's QML reads, its `question`, and its ends: OK or Apply with an answer."""

    question: dict = {}    # what the window opens with; each kind names its own fields

    answered = QtCore.Signal("QVariant")    # OK, with what the window's QML hands on
    applied = QtCore.Signal("QVariant")    # Apply, with the same: the window stays open

    def refused(self, answer) -> bool:
        """Whether the kind refuses `answer`, having said why; the window then stays as it is."""
        return False

    def reasked(self, question: dict) -> None:
        """The asker's reply to an Apply, a new `question` the kind then shows."""
        self.question = question

    @QtCore.Slot("QVariant")
    def accept(self, answer) -> None:
        """OK: the window closes, then its asker gets `answer`, a JavaScript object as a dict."""
        answer = answer.toVariant() if isinstance(answer, QtQml.QJSValue) else answer
        if not self.refused(answer):
            self.answered.emit(answer)

    @QtCore.Slot("QVariant")
    def apply(self, answer) -> None:
        """Apply: the asker gets `answer` and the window stays open."""
        answer = answer.toVariant() if isinstance(answer, QtQml.QJSValue) else answer
        if not self.refused(answer):
            self.applied.emit(answer)

    @QtCore.Slot()
    def reject(self) -> None:
        """Cancel, as Esc and the window's own close: it closes and its asker gets None."""
        self.windowCloseRequested.emit()


class DialogWindow(qmlviews.BaseQmlView):
    """A dialog window, each kind a subclass naming its QML and width: not modal, one open per kind."""

    STATE = DialogState    # what the kind's QML reads: a kind with more to show names its own
    _content_height = 0.0    # the QML's own height, in design px, once it has loaded
    _then = None    # the asker's, called once at the close
    _answer = None    # OK's answer; any other close leaves None, a Cancel

    def __init__(self, title: str, question: dict, then) -> None:
        super().__init__(state=self.STATE(question=question))
        self._then = then
        self.sharedState().setParent(self)    # deleted by Qt with the window, on the main thread
        self.sharedState().answered.connect(self._accept)
        self.sharedState().applied.connect(self._apply)
        self.setTitle(title)

    @classmethod
    def ask(cls, owner, title: str, question: dict, then) -> "DialogWindow":
        """`question` in this kind, replacing an open one: `then` at each Apply, once at the close."""
        shown = _open.get(cls)
        if shown is not None:
            try:
                shown.close()    # its asker's Cancel, as Houdini's Create Asset replaces its open window
            except RuntimeError:    # deleted already
                pass
        window = _open[cls] = cls(title, question, then)
        owner.destroyed.connect(window.close)    # it never outlives the pane it answers
        window.show()    # as Houdini shows its Preferences window
        window.raise_()
        window.requestActivate()
        return window

    def setupEngine(self) -> None:
        """Followed from before the QML loads, so its first height sizes the window."""
        self.sharedState().contentHeightChanged.connect(self._fit_height)

    def unscaledDefaultSize(self) -> QtCore.QSize:
        """The kind's width, and its content's height, as Houdini's Create Asset window follows it."""
        return QtCore.QSize(self.DEFAULT_SIZE.width(),
                            math.ceil(self._content_height) or self.DEFAULT_SIZE.height())

    def _fit_height(self, height: float) -> None:
        self._content_height = height
        self.resize(self.width(), self.scaledDefaultSize().height())

    def _accept(self, answer) -> None:
        self._answer = answer
        self.close()

    @debug.guarded("DialogWindow.apply")
    def _apply(self, answer) -> None:
        reply = self._then(answer) if self._then is not None else None
        if reply is not None:    # the asker's new question: the window stays open on it
            self.sharedState().reasked(reply)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if _open.get(type(self)) is self:
            del _open[type(self)]
        self.deleteLater()    # as Houdini's windows do: Qt deletes it, on the main thread

    def event(self, event) -> bool:
        """After Qt's close has hidden the window, its asker gets the answer: a window it opens is on top."""
        closing = event.type() == QtCore.QEvent.Type.Close
        done = super().event(event)
        if closing and event.isAccepted():
            self._hand_on()
        return done

    @debug.guarded("DialogWindow.answer")
    def _hand_on(self) -> None:
        then, self._then = self._then, None
        if then is not None:
            then(self._answer)
