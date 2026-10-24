"""Web 页面与 Python 之间的 QWebChannel 桥接对象。"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class ReaderBridge(QObject):
    """由页面脚本调用，把事件转成 Qt 信号。"""

    ready = pyqtSignal()
    scroll_changed = pyqtSignal(float, bool)
    link_clicked = pyqtSignal(str)
    key_pressed = pyqtSignal(str, bool)
    page_turned = pyqtSignal(bool, bool)

    @pyqtSlot()
    def pageReady(self) -> None:  # noqa: N802 - 供 JS 调用
        self.ready.emit()

    @pyqtSlot(float, bool)
    def reportScroll(self, ratio: float, at_end: bool) -> None:  # noqa: N802
        self.scroll_changed.emit(float(ratio), bool(at_end))

    @pyqtSlot(str)
    def linkClicked(self, href: str) -> None:  # noqa: N802
        self.link_clicked.emit(href)

    @pyqtSlot(str, bool)
    def reportKey(self, key: str, shift: bool) -> None:  # noqa: N802
        self.key_pressed.emit(key, bool(shift))

    @pyqtSlot(bool, bool)
    def reportPageTurn(self, forward: bool, moved: bool) -> None:  # noqa: N802
        self.page_turned.emit(bool(forward), bool(moved))
