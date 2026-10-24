"""阅读视图：承载 QtWebEngine 页面、注入主题样式、处理跳转与页内高亮。"""

from __future__ import annotations

import json
from typing import Any, Callable

from PyQt6.QtCore import QEvent, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QMenu

from .book import Chapter
from .bridge import ReaderBridge
from .webassets import READER_JS, THEMES, theme_css


class _Page(QWebEnginePage):
    """拦截页面内导航，全部交由 Python 端解析。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeTyped:
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
        if not is_main_frame:
            return False
        target = url.toString()
        if target and not target.startswith("about:"):
            view = self.parent()
            if isinstance(view, ReaderView):
                view.handle_web_link(target)
        return False


class ReaderView(QWebEngineView):
    """单章渲染视图。"""

    chapter_rendered = pyqtSignal(int)
    link_activated = pyqtSignal(str)
    page_turn_requested = pyqtSignal(bool)
    nav_key = pyqtSignal(str, bool)
    scroll_changed = pyqtSignal(float, bool)
    find_requested = pyqtSignal()
    search_selection = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.theme = "light"
        self.font_size = 19
        self.line_height = 1.75
        self.max_width = 780
        self.justify = True

        self._current = -1
        self._applied_css: set[int] = set()
        self._pending: dict[str, Any] | None = None
        self._bridge = ReaderBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._web_page = _Page(self)
        self._web_page.setWebChannel(self._channel)
        self.setPage(self._web_page)

        settings = self._web_page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)

        self.loadFinished.connect(self._on_load_finished)
        self._bridge.link_clicked.connect(self.link_activated.emit)
        self._bridge.key_pressed.connect(self.nav_key.emit)
        self._bridge.scroll_changed.connect(self.scroll_changed.emit)
        self._bridge.page_turned.connect(self._on_page_turned)
        self._web_page.setBackgroundColor(self.background())

    # -- 主题 ---------------------------------------------------------------

    def css(self) -> str:
        return theme_css(self.theme, self.font_size, self.line_height, self.max_width, self.justify)

    def _signature(self) -> tuple:
        return (self.theme, self.font_size, self.line_height, self.max_width, self.justify)

    def background(self) -> QColor:
        return QColor(THEMES.get(self.theme, THEMES["light"])["bg"])

    def set_style(
        self,
        theme: str | None = None,
        font_size: int | None = None,
        line_height: float | None = None,
        max_width: int | None = None,
        justify: bool | None = None,
    ) -> None:
        changed = False
        if theme is not None and theme != self.theme:
            self.theme = theme
            changed = True
        if font_size is not None:
            value = max(10, min(42, int(font_size)))
            if value != self.font_size:
                self.font_size = value
                changed = True
        if line_height is not None:
            value = max(1.1, min(2.6, round(float(line_height), 2)))
            if value != self.line_height:
                self.line_height = value
                changed = True
        if max_width is not None:
            value = max(420, min(1600, int(max_width)))
            if value != self.max_width:
                self.max_width = value
                changed = True
        if justify is not None and bool(justify) != self.justify:
            self.justify = bool(justify)
            changed = True
        if not changed:
            return
        self._web_page.setBackgroundColor(self.background())
        self._applied_css.clear()
        self._apply_css()

    def _apply_css(self) -> None:
        self._run(
            "var s=document.getElementById('er-theme');"
            "if(!s){s=document.createElement('style');s.id='er-theme';"
            "(document.head||document.documentElement).appendChild(s);}"
            f"s.textContent={json.dumps(self.css())};"
        )
        if self._current >= 0:
            self._applied_css.add(self._current)

    # -- 章节 ---------------------------------------------------------------

    def open_chapter(
        self,
        chapter: Chapter,
        anchor: str | None = None,
        ratio: float | None = None,
        mark_index: int | None = None,
        block: tuple[str, float] | None = None,
        term: str | None = None,
        match_case: bool = False,
        whole_word: bool = False,
    ) -> None:
        self._pending = {
            "index": chapter.index,
            "anchor": anchor,
            "ratio": ratio,
            "mark_index": mark_index,
            "block": block,
            "term": term,
            "match_case": match_case,
            "whole_word": whole_word,
        }
        self._current = chapter.index
        self._applied_css.discard(chapter.index)
        self._web_page.setBackgroundColor(self.background())
        self.load(QUrl.fromLocalFile(str(chapter.file)))

    @property
    def current_chapter(self) -> int:
        return self._current

    def _on_load_finished(self, ok: bool) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        if not ok:
            return
        self._run(READER_JS)
        self._apply_css()
        term = pending["term"]
        if term:
            self._highlight(term, pending["match_case"], pending["whole_word"],
                            lambda _count: self._restore_position(pending))
        else:
            self._restore_position(pending)
        self.chapter_rendered.emit(pending["index"])

    def _restore_position(self, pending: dict[str, Any]) -> None:
        block = pending["block"]
        if block is not None:
            block_id, fraction = block
            self._run(
                "window.ER && window.ER.scrollToBlock("
                f"{json.dumps(block_id)}, {float(fraction):.4f});"
            )
        elif pending["anchor"]:
            self._run(f"window.ER && window.ER.goToId({json.dumps(pending['anchor'])});")
        elif pending["ratio"] is not None:
            self._run(f"window.ER && window.ER.scrollToRatio({float(pending['ratio']):.5f});")
        index = pending["mark_index"]
        if index is not None:
            self._run(
                "window.ER && window.ER.focusMarkAt ? "
                f"window.ER.focusMarkAt({int(index)}) : window.ER && window.ER.focusMark(1);"
            )

    def _on_page_turned(self, forward: bool, moved: bool) -> None:
        if not moved:
            self.page_turn_requested.emit(forward)

    # -- 高亮 ---------------------------------------------------------------

    def _highlight(
        self,
        term: str,
        match_case: bool,
        whole_word: bool,
        callback: Callable[[Any], None] | None = None,
    ) -> None:
        script = (
            "window.ER ? window.ER.highlight("
            f"{json.dumps(term)}, {str(bool(match_case)).lower()}, "
            f"{str(bool(whole_word)).lower()}, 0) : 0"
        )
        self._run(script, callback)

    def apply_highlights(self, term: str, match_case: bool, whole_word: bool) -> None:
        if term:
            self._highlight(term, match_case, whole_word)
        else:
            self.clear_highlights()

    def clear_highlights(self) -> None:
        self._run("window.ER && window.ER.clearMarks();")

    def focus_mark(self, direction: int) -> None:
        self._run(f"window.ER && window.ER.focusMark({int(direction)});")

    # -- 滚动 ---------------------------------------------------------------

    def scroll_page(self, forward: bool) -> None:
        self._run(f"window.ER && window.ER.page({1 if forward else -1});")

    def scroll_line(self, forward: bool) -> None:
        self._run(f"window.scrollBy(0, {60 if forward else -60});")

    def scroll_ratio(self, ratio: float) -> None:
        self._run(f"window.ER && window.ER.scrollToRatio({float(ratio):.5f});")

    def scroll_to_id(self, anchor: str) -> None:
        self._run(f"window.ER && window.ER.goToId({json.dumps(anchor)});")

    def handle_web_link(self, target: str) -> None:
        self.link_activated.emit(target)

    def show_placeholder(self) -> None:
        """关闭书籍后显示的欢迎页。"""

        bg = THEMES.get(self.theme, THEMES["light"])
        document = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{height:100%;margin:0}
body{display:flex;align-items:center;justify-content:center;
 background:BG;color:MUTED;
 font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif}
h1{font-size:22px;font-weight:600;margin:0 0 10px}
p{font-size:13px;margin:4px 0}
kbd{background:rgba(127,127,127,.18);border-radius:4px;padding:1px 6px;font-family:inherit}
</style></head><body><div style="text-align:center">
<h1>未打开书籍</h1>
<p>使用 <kbd>Ctrl+O</kbd> 打开 EPUB，或把文件拖到窗口中</p>
<p>打开后可用 <kbd>Ctrl+F</kbd> 搜索全书内容</p>
</div></body></html>"""
        document = document.replace("BG", bg["bg"]).replace("MUTED", bg["muted"])
        self._current = -1
        self._pending = None
        self.setHtml(document)
        self._web_page.setBackgroundColor(self.background())

    # -- 内部 ---------------------------------------------------------------

    def _run(self, script: str, callback: Callable[[Any], None] | None = None) -> None:
        if callback is None:
            self._web_page.runJavaScript(script)
        else:
            self._web_page.runJavaScript(script, callback)

    # -- 键盘与右键菜单 -----------------------------------------------------

    _NAV_KEYS = {
        Qt.Key.Key_Left: ("pageleft",),
        Qt.Key.Key_Right: ("pageright",),
        Qt.Key.Key_PageUp: ("pageup",),
        Qt.Key.Key_PageDown: ("pagedown",),
        Qt.Key.Key_Up: ("lineup",),
        Qt.Key.Key_Down: ("linedown",),
        Qt.Key.Key_Home: ("home",),
        Qt.Key.Key_End: ("end",),
        Qt.Key.Key_Space: ("space",),
        Qt.Key.Key_F3: ("findnext",),
    }

    def event(self, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
            if self._handle_key(event, emit_only=True):
                return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._handle_key(event, emit_only=False):
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_key(self, event: QKeyEvent, emit_only: bool) -> bool:
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        key = event.key()
        if key not in self._NAV_KEYS:
            return False
        name = self._NAV_KEYS[key][0]
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if emit_only:
            return True
        self.nav_key.emit(name, not shift)
        return True

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        act_copy = menu.addAction("复制")
        act_select = menu.addAction("全选")
        menu.addSeparator()
        act_search_sel = menu.addAction("搜索选中内容…")
        act_find = menu.addAction("在本书中查找…")
        chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            self._web_page.triggerAction(QWebEnginePage.WebAction.Copy)
        elif chosen is act_select:
            self._web_page.triggerAction(QWebEnginePage.WebAction.SelectAll)
        elif chosen is act_search_sel:
            self._web_page.selectedText()
            self._run(
                "window.getSelection ? window.getSelection().toString() : ''",
                self._selection_text,
            )
        elif chosen is act_find:
            self.find_requested.emit()

    def _selection_text(self, text: Any) -> None:
        if isinstance(text, str):
            cleaned = " ".join(text.split())
            if cleaned:
                self.search_selection.emit(cleaned)
