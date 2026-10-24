"""侧边栏面板：目录树与搜索结果列表。"""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPalette,
    QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .book import TocEntry
from .search import SearchHit

_CHAPTER_ROLE = Qt.ItemDataRole.UserRole + 1
_ANCHOR_ROLE = Qt.ItemDataRole.UserRole + 2
_HIT_ROLE = Qt.ItemDataRole.UserRole + 3

ROW_HEIGHT = 76


class TocPanel(QWidget):
    """章节目录，支持层级显示与当前章节同步。"""

    chapter_selected = pyqtSignal(int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("筛选章节标题…")
        self.filter_edit.setClearButtonEnabled(True)
        layout.addWidget(self.filter_edit)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        self.tree.setIndentation(14)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setWordWrap(False)
        layout.addWidget(self.tree, 1)

        self.filter_edit.textChanged.connect(self._apply_filter)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemActivated.connect(self._on_clicked)
        self._current_chapter = -1
        self._items: list[QTreeWidgetItem] = []

    def populate(self, toc: list[TocEntry], chapter_titles: list[str]) -> None:
        self.tree.clear()
        self._items = []
        stack: list[tuple[int, QTreeWidgetItem]] = []
        last_leaf_index = -1

        for entry in toc:
            item = QTreeWidgetItem([entry.title or "未命名"])
            chapter = entry.chapter
            if chapter is None and last_leaf_index >= 0:
                chapter = last_leaf_index
            if chapter is not None:
                last_leaf_index = chapter
            item.setData(0, _CHAPTER_ROLE, chapter)
            item.setData(0, _ANCHOR_ROLE, entry.anchor or "")
            font = item.font(0)
            font.setBold(entry.level <= 1)
            item.setFont(0, font)
            if chapter is not None and 0 <= chapter < len(chapter_titles):
                item.setToolTip(0, chapter_titles[chapter])
            while stack and stack[-1][0] >= entry.level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            stack.append((entry.level, item))
            self._items.append(item)

        self.tree.expandToDepth(1)
        self._current_chapter = -1

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(row), needle)

    def _filter_item(self, item: QTreeWidgetItem, needle: str) -> bool:
        visible = not needle or needle in item.text(0).lower()
        child_visible = False
        for index in range(item.childCount()):
            if self._filter_item(item.child(index), needle):
                child_visible = True
        item.setHidden(not (visible or child_visible))
        if needle and child_visible:
            item.setExpanded(True)
        return visible or child_visible

    def set_current_chapter(self, chapter: int) -> None:
        if chapter == self._current_chapter:
            return
        self._current_chapter = chapter
        target = None
        for item in self._items:
            if item.data(0, _CHAPTER_ROLE) == chapter:
                target = item
                break
        if target is None:
            return
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(target)
        self.tree.blockSignals(False)
        parent = target.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.scrollToItem(target, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        chapter = item.data(0, _CHAPTER_ROLE)
        if chapter is None:
            return
        anchor = item.data(0, _ANCHOR_ROLE) or ""
        self.chapter_selected.emit(int(chapter), str(anchor))


class _HitDelegate(QStyledItemDelegate):
    """绘制搜索结果：章节标题行 + 带高亮的上下文摘要。

    全部使用 QFontMetrics 手工排版，避免在 paint 中使用 QTextDocument。
    """

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        width = option.rect.width()
        return QSize(width if width > 0 else 260, ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        data = index.data(_HIT_ROLE)
        if not isinstance(data, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setClipRect(option.rect)

        palette = option.palette
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        if selected:
            painter.fillRect(option.rect, highlight)
            title_color = palette.color(QPalette.ColorRole.HighlightedText)
            body_color = title_color
            mark_bg = QColor(255, 255, 255, 70)
        else:
            if hovered:
                painter.fillRect(option.rect, palette.color(QPalette.ColorRole.AlternateBase))
            title_color = palette.color(QPalette.ColorRole.Text)
            body_color = palette.color(QPalette.ColorRole.PlaceholderText)
            mark_bg = QColor("#ffe06a")
            painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1))
            painter.drawLine(
                option.rect.left() + 12,
                option.rect.bottom(),
                option.rect.right() - 12,
                option.rect.bottom(),
            )

        rect = option.rect.adjusted(12, 9, -12, -9)

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        title_metrics = QFontMetrics(title_font)
        title_height = title_metrics.height()

        percent_text = f"{int(data.get('percent', 0))}%"
        percent_font = QFont(option.font)
        if percent_font.pointSizeF() > 1:
            percent_font.setPointSizeF(max(7.0, percent_font.pointSizeF() - 1.0))
        percent_metrics = QFontMetrics(percent_font)
        percent_width = percent_metrics.horizontalAdvance(percent_text) + 8

        painter.setPen(title_color)
        title = title_metrics.elidedText(
            str(data.get("chapter_title", "")),
            Qt.TextElideMode.ElideRight,
            max(20, rect.width() - percent_width),
        )
        painter.drawText(
            QRect(rect.left(), rect.top(), rect.width() - percent_width, title_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title,
        )
        painter.setFont(percent_font)
        painter.setPen(body_color)
        painter.drawText(
            QRect(rect.right() - percent_width, rect.top(), percent_width, title_height),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            percent_text,
        )

        body_top = rect.top() + title_height + 4
        body_rect = QRect(rect.left(), body_top, rect.width(), rect.height() - title_height - 4)
        self._draw_snippet(painter, body_rect, option.font, data, body_color, mark_bg, selected)
        painter.restore()

    def _draw_snippet(
        self,
        painter: QPainter,
        rect: QRect,
        font: QFont,
        data: dict,
        color: QColor,
        mark_bg: QColor,
        selected: bool,
    ) -> None:
        metrics = QFontMetrics(font)
        painter.setFont(font)
        line_height = metrics.height()
        max_lines = max(1, rect.height() // max(1, line_height))
        width = rect.width()
        ellipsis = "…"

        prefix = str(data.get("prefix", ""))
        matched = str(data.get("matched", ""))
        suffix = str(data.get("suffix", ""))

        def advance(text: str) -> int:
            return metrics.horizontalAdvance(text)

        # 通过裁剪（从两端截断）保证总宽度可放入区域
        budget = width
        while advance(prefix + matched + suffix) > budget * max_lines and (prefix or suffix):
            if len(prefix) >= len(suffix) and prefix:
                prefix = ellipsis + prefix[2:] if len(prefix) > 2 else ""
            elif suffix:
                suffix = suffix[:-2] + ellipsis if len(suffix) > 2 else ""
            elif prefix:
                prefix = prefix[2:] if len(prefix) > 2 else ""
        if advance(matched) > width:
            matched = metrics.elidedText(matched, Qt.TextElideMode.ElideMiddle, width)

        segments: list[tuple[str, QColor | None, bool]] = [
            (prefix, None, selected),
            (matched, mark_bg, False),
            (suffix, None, selected),
        ]

        x = rect.left()
        y = rect.top() + metrics.ascent()
        bottom = rect.bottom()

        for text, background, italic in segments:
            if not text:
                continue
            run_font = QFont(font)
            if italic:
                run_font.setItalic(True)
            run_metrics = QFontMetrics(run_font)
            painter.setFont(run_font)
            index = 0
            while index < len(text):
                if y > bottom:
                    return
                remaining = rect.right() - x
                if remaining <= 2:
                    x = rect.left()
                    y += line_height
                    continue
                # 逐字贪心填充，兼容中英文混排
                take = 0
                used = 0
                while index + take < len(text):
                    char = text[index + take]
                    char_width = run_metrics.horizontalAdvance(char)
                    if used + char_width > remaining:
                        break
                    used += char_width
                    take += 1
                if take == 0:
                    x = rect.left()
                    y += line_height
                    continue
                piece = text[index: index + take]
                piece_rect = QRect(x, y - run_metrics.ascent(), used, run_metrics.height())
                if background is not None:
                    painter.fillRect(piece_rect, background)
                painter.setPen(color)
                painter.drawText(
                    QRect(x, piece_rect.top(), used, run_metrics.height()),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    piece,
                )
                x += used
                index += take
                if index < len(text) and x >= rect.right() - 2:
                    x = rect.left()
                    y += line_height


class SearchPanel(QWidget):
    """搜索输入、选项、进度与结果列表。"""

    search_requested = pyqtSignal(str, bool, bool)
    hit_activated = pyqtSignal(int, int)
    cleared = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.entry = QLineEdit(self)
        self.entry.setPlaceholderText("在全书范围内搜索…")
        self.entry.setClearButtonEnabled(True)
        row.addWidget(self.entry, 1)
        self.button = QPushButton("搜索", self)
        self.button.setDefault(True)
        row.addWidget(self.button)
        layout.addLayout(row)

        options = QHBoxLayout()
        options.setSpacing(10)
        self.case_box = QCheckBox("区分大小写", self)
        self.word_box = QCheckBox("匹配整词", self)
        options.addWidget(self.case_box)
        options.addWidget(self.word_box)
        options.addStretch(1)
        layout.addLayout(options)

        self.status = QLabel("输入关键词后回车开始搜索", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.list = QListWidget(self)
        self.list.setItemDelegate(_HitDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(0)
        self.list.setWordWrap(False)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMouseTracking(True)
        layout.addWidget(self.list, 1)

        self.entry.returnPressed.connect(self._emit_search)
        self.button.clicked.connect(self._emit_search)
        self.entry.textChanged.connect(self._on_text_changed)
        self.list.itemActivated.connect(self._on_activated)
        self.list.itemClicked.connect(self._on_activated)
        self.word_box.toggled.connect(lambda _state: self._emit_search())
        self.case_box.toggled.connect(lambda _state: self._emit_search())
        self._hits: list[SearchHit] = []

    # -- 状态 ---------------------------------------------------------------

    def focus_entry(self) -> None:
        self.entry.setFocus()
        self.entry.selectAll()

    def set_query(self, text: str, trigger: bool = True) -> None:
        self.entry.setText(text)
        if trigger:
            self._emit_search()

    def set_busy(self, busy: bool) -> None:
        self.button.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
            self.status.setText("正在搜索…")
        else:
            self.progress.setRange(0, 100)

    def set_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def hits(self) -> list[SearchHit]:
        return list(self._hits)

    def clear_results(self) -> None:
        self._hits = []
        self.list.clear()
        self.status.setText("输入关键词后回车开始搜索")

    def show_results(self, hits: list[SearchHit], chapter_titles: list[str], per_chapter: dict[int, int]) -> None:
        self._hits = list(hits)
        self.list.clear()
        if not hits:
            self.status.setText("没有找到匹配的内容")
            return
        total = len(hits)
        chapters = len({hit.chapter for hit in hits})
        self.status.setText(f"找到 {total} 处匹配，分布在 {chapters} 个章节")
        for hit in hits:
            title = chapter_titles[hit.chapter] if 0 <= hit.chapter < len(chapter_titles) else ""
            item = QListWidgetItem()
            item.setData(_CHAPTER_ROLE, hit.chapter)
            item.setData(
                _HIT_ROLE,
                {
                    "chapter_title": title,
                    "prefix": hit.prefix,
                    "matched": hit.matched,
                    "suffix": hit.suffix,
                    "snippet": hit.snippet,
                    "percent": per_chapter.get(hit.chapter, 0),
                },
            )
            item.setToolTip(f"{title}\n…{hit.snippet}…")
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def current_row(self) -> int:
        return self.list.currentRow()

    def select_row(self, row: int) -> None:
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)

    def _on_text_changed(self, text: str) -> None:
        if not text.strip() and self.list.count():
            self.clear_results()
            self.cleared.emit()

    def _emit_search(self) -> None:
        query = self.entry.text().strip()
        if not query:
            self.clear_results()
            self.cleared.emit()
            return
        self.search_requested.emit(query, self.case_box.isChecked(), self.word_box.isChecked())

    def _on_activated(self, item: QListWidgetItem) -> None:
        chapter = item.data(_CHAPTER_ROLE)
        if chapter is None:
            return
        self.hit_activated.emit(int(chapter), self.list.row(item))
