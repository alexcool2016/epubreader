"""全文搜索：在后台线程中扫描所有章节，支持整词/大小写/结果上限。

搜索不依赖 Qt，便于单独测试；同时提供 Qt 线程封装。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .book import Chapter, EpubBook


@dataclass(slots=True)
class SearchHit:
    """一条命中结果。"""

    chapter: int
    offset: int
    snippet_start: int
    snippet_end: int
    snippet: str
    prefix: str
    matched: str
    suffix: str
    exact: bool  # 片段是否在句内精确匹配（用于决定是否插入 <mark>）

    @property
    def anchor_prefix(self) -> str:
        return self.prefix.lstrip()


@dataclass(slots=True)
class SearchOptions:
    query: str
    match_case: bool = False
    whole_word: bool = False
    limit: int = 500


_ASCII_WORD = re.compile(r"[0-9A-Za-z_]")
_BREAK_CHARS = "。！？；，、：!?;,:.\n"


def _build_pattern(query: str, match_case: bool, whole_word: bool) -> re.Pattern[str] | None:
    if not query:
        return None
    escaped = re.escape(query)
    if whole_word:
        # 仅对 ASCII 单字加词边界；中日韩文字本身即为 \w，加 \b 会导致无法匹配
        if _ASCII_WORD.match(query[0]):
            escaped = r"(?<![0-9A-Za-z_])" + escaped
        if _ASCII_WORD.match(query[-1]):
            escaped = escaped + r"(?![0-9A-Za-z_])"
    flags = re.IGNORECASE if not match_case else 0
    try:
        return re.compile(escaped, flags)
    except re.error:
        return None


def _widen_left(text: str, start: int, width: int) -> int:
    """从 start 向左找自然的断句位置。"""

    limit = max(0, start - width)
    for pos in range(start - 1, limit - 1, -1):
        char = text[pos]
        if char == "\n":
            return pos + 1
        if char in _BREAK_CHARS:
            return pos + 1
    return limit


def _widen_right(text: str, end: int, width: int) -> int:
    limit = min(len(text), end + width)
    for pos in range(end, limit):
        char = text[pos]
        if char == "\n":
            return pos
        if char in _BREAK_CHARS:
            return pos + 1
    return limit


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def _snippet(text: str, start: int, end: int, width: int = 48) -> tuple[int, int, str, str, str]:
    """截取命中附近的上下文，尽量在句读处断开，返回（左界, 右界, 前缀, 命中, 后缀）。"""

    left = _widen_left(text, start, width)
    right = _widen_right(text, end, width)
    return left, right, _clean(text[left:start]), _clean(text[start:end]), _clean(text[end:right])


def search_book(
    book: EpubBook,
    options: SearchOptions,
    cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[SearchHit]:
    """扫描全书，返回至多 options.limit 条结果。"""

    pattern = _build_pattern(options.query, options.match_case, options.whole_word)
    if pattern is None:
        return []
    results: list[SearchHit] = []
    total = len(book.chapters)
    for chapter in book.chapters:
        if cancel is not None and cancel():
            break
        if on_progress is not None:
            on_progress(chapter.index + 1, total)
        for match in pattern.finditer(chapter.text):
            start, end = match.span()
            if start == end:
                continue
            left, right, prefix, matched, suffix = _snippet(chapter.text, start, end)
            snippet = prefix + matched + suffix
            results.append(
                SearchHit(
                    chapter=chapter.index,
                    offset=start,
                    snippet_start=left,
                    snippet_end=right,
                    snippet=snippet,
                    prefix=prefix,
                    matched=matched or options.query,
                    suffix=suffix,
                    exact=bool(matched),
                )
            )
            if len(results) >= options.limit:
                return results
    return results


def contiguous_runs(chapters: Sequence[Chapter], chapter_index: int, hits: Iterable[SearchHit]) -> list[tuple[int, int]]:
    """供高亮使用：把同一章内的命中合并为连续区间。"""

    spans: list[tuple[int, int]] = []
    chapter = chapters[chapter_index]
    for hit in hits:
        if hit.chapter != chapter_index:
            continue
        length = len(hit.matched) if hit.exact else len(hit.matched)
        spans.append((hit.offset, min(hit.offset + max(length, 1), len(chapter.text))))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# ---------------------------------------------------------------------------
# Qt 线程封装
# ---------------------------------------------------------------------------

try:  # 允许不安装 Qt 时仍可使用纯逻辑
    from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
except Exception:  # pragma: no cover
    QObject = object  # type: ignore[assignment,misc]
    QThread = object  # type: ignore[assignment,misc]

    def pyqtSignal(*args, **kwargs):  # type: ignore[misc]
        return None

    def pyqtSlot(*args, **kwargs):  # type: ignore[misc]
        def decorator(func):
            return func

        return decorator


def _qt_search_worker_class():
    """延迟定义，避免在 Qt 缺失时报错。"""

    class SearchWorker(QThread):
        """在后台执行全文搜索。"""

        finished_results = pyqtSignal(int, list)
        progressed = pyqtSignal(int, int)

        def __init__(self, book: EpubBook, options: SearchOptions, token: int) -> None:
            super().__init__()
            self._book = book
            self._options = options
            self._token = token
            self._cancelled = False

        def cancel(self) -> None:
            self._cancelled = True

        def run(self) -> None:  # noqa: D102
            hits = search_book(
                self._book,
                self._options,
                cancel=lambda: self._cancelled or self.isInterruptionRequested(),
                on_progress=lambda done, total: self.progressed.emit(done, total),
            )
            if not self._cancelled and not self.isInterruptionRequested():
                self.finished_results.emit(self._token, hits)

    return SearchWorker


class SearchService(QObject):
    """管理搜索线程的启动、取消与结果分发。"""

    started = pyqtSignal(int)
    progressed = pyqtSignal(int, int)
    finished_search = pyqtSignal(int, list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = None
        self._thread_class = _qt_search_worker_class()
        self._token = 0

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def start(self, book: EpubBook, options: SearchOptions) -> int | None:
        if not options.query.strip():
            return None
        self.cancel()
        self._token += 1
        token = self._token
        worker = self._thread_class(book, options, token)
        worker.progressed.connect(self.progressed)
        worker.finished_results.connect(self.finished_search)
        worker.finished_results.connect(self._cleanup)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        self.started.emit(token)
        worker.start()
        return token

    def cancel(self) -> None:
        worker, self._worker = self._worker, None
        if worker is None:
            return
        worker.cancel()
        worker.requestInterruption()
        if not worker.wait(3000):
            worker.terminate()
            worker.wait(1000)

    def _cleanup(self, *_args) -> None:
        worker, self._worker = self._worker, None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
