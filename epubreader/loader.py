"""在后台线程中解析 EPUB，避免打开大文件时界面卡死。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .book import EpubBook, EpubError


class BookLoader(QThread):
    """解析一本书并返回 :class:`EpubBook` 实例。"""

    progress = pyqtSignal(int, int, str)
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: str | Path, parent=None) -> None:
        super().__init__(parent)
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def run(self) -> None:  # noqa: D102
        try:
            book = EpubBook.open(self._path, progress=self._report)
        except EpubError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # 兜底，防止线程内异常导致崩溃
            self.failed.emit(f"解析失败：{exc}")
            return
        self.loaded.emit(book)

    def _report(self, done: int, total: int, message: str) -> None:
        self.progress.emit(done, total, message)
