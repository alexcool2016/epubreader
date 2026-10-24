"""主窗口：菜单、工具栏、侧边栏（目录/搜索）、阅读区与状态栏。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
    QCheckBox,
    QSizePolicy,
)

from . import __version__
from .book import Chapter, EpubBook, EpubError, TocEntry
from .loader import BookLoader
from .panels import SearchPanel, TocPanel
from .paths import ProgressStore, app_data_dir, book_cache_key, resource_path
from .reader import ReaderView
from .search import SearchHit, SearchOptions, SearchService

SUPPORTED_SUFFIXES = {".epub"}


def app_icon() -> QIcon:
    """程序图标（源码运行与打包后都能找到）。"""

    for name in ("app.ico", "app.png"):
        path = resource_path("assets", name)
        if path.exists():
            return QIcon(str(path))
    return QIcon()


class SettingsDialog(QDialog):
    """字体、行距、主题与版心宽度设置。"""

    def __init__(self, parent: QWidget, theme: str, font_size: int, line_height: float,
                 max_width: int, justify: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("阅读设置")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.theme_box = QComboBox(self)
        for key, label in (
            ("light", "明亮"),
            ("sepia", "羊皮纸"),
            ("dark", "夜间"),
            ("green", "护眼"),
        ):
            self.theme_box.addItem(label, key)
        index = self.theme_box.findData(theme)
        self.theme_box.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("主题", self.theme_box)

        self.size_spin = QSpinBox(self)
        self.size_spin.setRange(12, 40)
        self.size_spin.setSuffix(" px")
        self.size_spin.setValue(font_size)
        form.addRow("字号", self.size_spin)

        self.line_spin = QDoubleSpinBox(self)
        self.line_spin.setRange(1.2, 2.4)
        self.line_spin.setSingleStep(0.05)
        self.line_spin.setDecimals(2)
        self.line_spin.setValue(line_height)
        form.addRow("行距", self.line_spin)

        self.width_spin = QSpinBox(self)
        self.width_spin.setRange(480, 1400)
        self.width_spin.setSingleStep(20)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(max_width)
        form.addRow("版心宽度", self.width_spin)

        self.justify_box = QCheckBox("两端对齐", self)
        self.justify_box.setChecked(justify)
        form.addRow("", self.justify_box)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "theme": self.theme_box.currentData(),
            "font_size": self.size_spin.value(),
            "line_height": self.line_spin.value(),
            "max_width": self.width_spin.value(),
            "justify": self.justify_box.isChecked(),
        }


class MainWindow(QMainWindow):
    """EPUB 阅读器主窗口。"""

    def __init__(self, startup_file: str | None = None) -> None:
        super().__init__()
        self.book: EpubBook | None = None
        self._book_key: str | None = None
        self._chapter = -1
        self._ratio = 0.0
        self._hits: list[SearchHit] = []
        self._hit_index = -1
        self._search_term = ""
        self._pending_link: str | None = None
        self._loader: BookLoader | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(900)
        self._save_timer.timeout.connect(self._persist_progress)

        self.settings = QSettings("EpubReader", "EpubReader")
        self.progress_store = ProgressStore()
        self.splitter_state = self.settings.value("ui/splitter")

        self.reader = ReaderView(self)
        self.setCentralWidget(self.reader)
        self.search_service = SearchService(self)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_sidebar()
        self._build_statusbar()
        self._connect_signals()
        self._restore_settings()
        self._update_actions()

        self.setAcceptDrops(True)
        icon = app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.setWindowTitle("EPUB 阅读器")
        self.resize(1240, 820)
        if startup_file:
            QTimer.singleShot(120, lambda: self.open_path(startup_file))

    # -- 构建界面 -----------------------------------------------------------

    def _build_actions(self) -> None:
        self.act_open = QAction("打开(&O)…", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.setStatusTip("打开一个 EPUB 文件")
        self.act_open.triggered.connect(self.open_dialog)

        self.act_recent = QAction("最近打开", self)

        self.act_close = QAction("关闭当前书籍", self)
        self.act_close.setShortcut("Ctrl+W")
        self.act_close.triggered.connect(self.close_book)

        self.act_quit = QAction("退出(&X)", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_find = QAction("全文搜索", self)
        self.act_find.setShortcut(QKeySequence.StandardKey.Find)
        self.act_find.setStatusTip("在整本书中搜索文字")
        self.act_find.triggered.connect(self.show_search)

        self.act_find_next = QAction("下一个匹配", self)
        self.act_find_next.setShortcut("F3")
        self.act_find_next.triggered.connect(lambda: self._cycle_hit(1))

        self.act_find_prev = QAction("上一个匹配", self)
        self.act_find_prev.setShortcut("Shift+F3")
        self.act_find_prev.triggered.connect(lambda: self._cycle_hit(-1))

        self.act_clear_search = QAction("清除搜索高亮", self)
        self.act_clear_search.setShortcut("Esc")
        self.act_clear_search.triggered.connect(self.clear_search)

        self.act_prev_chapter = QAction("上一章", self)
        self.act_prev_chapter.setShortcut("Ctrl+Up")
        self.act_prev_chapter.triggered.connect(lambda: self.goto_chapter(self._chapter - 1))

        self.act_next_chapter = QAction("下一章", self)
        self.act_next_chapter.setShortcut("Ctrl+Down")
        self.act_next_chapter.triggered.connect(lambda: self.goto_chapter(self._chapter + 1))

        self.act_page_prev = QAction("上一页", self)
        self.act_page_prev.setShortcut("PageUp")
        self.act_page_prev.triggered.connect(lambda: self.reader.scroll_page(False))

        self.act_page_next = QAction("下一页", self)
        self.act_page_next.setShortcut("PageDown")
        self.act_page_next.triggered.connect(lambda: self.reader.scroll_page(True))

        self.act_zoom_in = QAction("放大字号", self)
        self.act_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.act_zoom_in.triggered.connect(lambda: self.change_font_size(1))

        self.act_zoom_out = QAction("缩小字号", self)
        self.act_zoom_out.setShortcut("Ctrl+-")
        self.act_zoom_out.triggered.connect(lambda: self.change_font_size(-1))

        self.act_zoom_reset = QAction("重置字号", self)
        self.act_zoom_reset.setShortcut("Ctrl+0")
        self.act_zoom_reset.triggered.connect(lambda: self.reader.set_style(font_size=19))

        self.act_settings = QAction("阅读设置…", self)
        self.act_settings.setShortcut("Ctrl+,")
        self.act_settings.triggered.connect(self.open_settings)

        self.act_toc = QAction("目录", self)
        self.act_toc.setCheckable(True)
        self.act_toc.setChecked(True)
        self.act_toc.setShortcut("Ctrl+T")

        self.act_search_tab = QAction("搜索面板", self)
        self.act_search_tab.setCheckable(True)
        self.act_search_tab.setShortcut("Ctrl+Shift+F")

        self.act_fullscreen = QAction("全屏", self)
        self.act_fullscreen.setShortcut("F11")
        self.act_fullscreen.triggered.connect(self.toggle_fullscreen)

        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(self.show_about)

        self.act_shortcuts = QAction("快捷键", self)
        self.act_shortcuts.triggered.connect(self.show_shortcuts)

        self.act_home = QAction("本书开头", self)
        self.act_home.setShortcut("Home")
        self.act_home.triggered.connect(lambda: self.goto_chapter(0))

        self.act_end = QAction("本书结尾", self)
        self.act_end.setShortcut("End")
        self.act_end.triggered.connect(lambda: self.goto_chapter(self._chapter_count() - 1))

        self.theme_actions: dict[str, QAction] = {}
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        for key, label in (
            ("light", "明亮"),
            ("sepia", "羊皮纸"),
            ("dark", "夜间"),
            ("green", "护眼"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(key)
            action.triggered.connect(lambda _checked, k=key: self.reader.set_style(theme=k))
            self.theme_group.addAction(action)
            self.theme_actions[key] = action

    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar("主工具栏", self)
        self.toolbar.setIconSize(QSize(20, 20))
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.toolbar.addAction(self.act_open)
        self.toolbar.addAction(self.act_close)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_prev_chapter)
        self.toolbar.addAction(self.act_next_chapter)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.act_find)
        self.toolbar.addAction(self.act_zoom_out)
        self.toolbar.addAction(self.act_zoom_in)
        self.toolbar.addSeparator()

        self.chapter_combo = QComboBox(self)
        self.chapter_combo.setMinimumWidth(260)
        self.chapter_combo.setMaximumWidth(460)
        self.chapter_combo.setToolTip("快速跳转到章节")
        self.chapter_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.chapter_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.toolbar.addWidget(self.chapter_combo)
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)

    def _build_sidebar(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.toc_panel = TocPanel(self.tabs)
        self.search_panel = SearchPanel(self.tabs)
        self.tabs.addTab(self.toc_panel, "目录")
        self.tabs.addTab(self.search_panel, "搜索")

        self.dock = QDockWidget("导航", self)
        self.dock.setObjectName("navigationDock")
        self.dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.dock.setWidget(self.tabs)
        self.dock.setMinimumWidth(250)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self.act_toc.setChecked)
        self.act_toc.toggled.connect(self.dock.setVisible)
        self.act_search_tab.toggled.connect(self._toggle_search_tab)

    def _toggle_search_tab(self, checked: bool) -> None:
        if checked:
            self.dock.show()
            self.tabs.setCurrentWidget(self.search_panel)
            self.search_panel.focus_entry()
        else:
            self.tabs.setCurrentWidget(self.toc_panel)

    def _build_statusbar(self) -> None:
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self.status_label = QLabel("就绪", self)
        self.status.addWidget(self.status_label, 1)
        self.position_label = QLabel("", self)
        self.status.addPermanentWidget(self.position_label)
        self.zoom_label = QLabel("", self)
        self.status.addPermanentWidget(self.zoom_label)
        self._update_zoom_label()

    def _connect_signals(self) -> None:
        self.reader.chapter_rendered.connect(self._on_chapter_rendered)
        self.reader.link_activated.connect(self._on_link)
        self.reader.page_turn_requested.connect(self._on_page_turn)
        self.reader.nav_key.connect(self._on_nav_key)
        self.reader.scroll_changed.connect(self._on_scroll)
        self.reader.find_requested.connect(self.show_search)
        self.reader.search_selection.connect(self.search_selected_text)
        self.toc_panel.chapter_selected.connect(self._on_toc_activated)
        self.search_panel.search_requested.connect(self.start_search)
        self.search_panel.hit_activated.connect(self._on_hit_activated)
        self.search_panel.cleared.connect(self.clear_search)
        self.search_service.progressed.connect(self.search_panel.set_progress)
        self.search_service.finished_search.connect(self._on_search_finished)
        self.search_service.started.connect(lambda _token: self.search_panel.set_busy(True))

    # -- 设置 ---------------------------------------------------------------

    def _restore_settings(self) -> None:
        theme = self.settings.value("reader/theme", "light")
        font_size = int(self.settings.value("reader/font_size", 19))
        line_height = float(self.settings.value("reader/line_height", 1.75))
        max_width = int(self.settings.value("reader/max_width", 780))
        justify = str(self.settings.value("reader/justify", "true")).lower() in ("true", "1")
        self.reader.set_style(theme, font_size, line_height, max_width, justify)
        action = self.theme_actions.get(theme)
        if action is not None:
            action.setChecked(True)
        geometry = self.settings.value("ui/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings.value("ui/state")
        if state is not None:
            self.restoreState(state)
        if self.splitter_state is None:
            self.dock.resize(300, self.dock.height())
        self._refresh_recent_menu()

    def _remember_settings(self) -> None:
        self.settings.setValue("reader/theme", self.reader.theme)
        self.settings.setValue("reader/font_size", self.reader.font_size)
        self.settings.setValue("reader/line_height", self.reader.line_height)
        self.settings.setValue("reader/max_width", self.reader.max_width)
        self.settings.setValue("reader/justify", "true" if self.reader.justify else "false")
        self.settings.setValue("ui/geometry", self.saveGeometry())
        self.settings.setValue("ui/state", self.saveState())
        self.settings.sync()

    # -- 菜单 ---------------------------------------------------------------

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("文件(&F)")
        file_menu.addAction(self.act_open)
        self.recent_menu = file_menu.addMenu("最近打开")
        file_menu.addAction(self.act_close)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        nav_menu = bar.addMenu("导航(&G)")
        nav_menu.addAction(self.act_prev_chapter)
        nav_menu.addAction(self.act_next_chapter)
        nav_menu.addSeparator()
        nav_menu.addAction(self.act_page_prev)
        nav_menu.addAction(self.act_page_next)
        nav_menu.addSeparator()
        nav_menu.addAction(self.act_home)
        nav_menu.addAction(self.act_end)

        search_menu = bar.addMenu("搜索(&S)")
        search_menu.addAction(self.act_find)
        search_menu.addAction(self.act_find_next)
        search_menu.addAction(self.act_find_prev)
        search_menu.addSeparator()
        search_menu.addAction(self.act_clear_search)

        view_menu = bar.addMenu("视图(&V)")
        view_menu.addAction(self.act_toc)
        view_menu.addAction(self.act_search_tab)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("主题")
        for action in self.theme_actions.values():
            theme_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_reset)
        view_menu.addSeparator()
        view_menu.addAction(self.act_fullscreen)

        tools_menu = bar.addMenu("设置(&T)")
        tools_menu.addAction(self.act_settings)

        help_menu = bar.addMenu("帮助(&H)")
        help_menu.addAction(self.act_shortcuts)
        help_menu.addAction(self.act_about)

    # -- 打开文件 -----------------------------------------------------------

    def open_dialog(self) -> None:
        start_dir = str(self.settings.value("ui/last_dir", str(Path.home())))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 EPUB 文件",
            start_dir,
            "EPUB 电子书 (*.epub);;所有文件 (*.*)",
        )
        if path:
            self.settings.setValue("ui/last_dir", os.path.dirname(path))
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        target = Path(path)
        if not target.exists():
            QMessageBox.warning(self, "打开失败", f"文件不存在：\n{target}")
            return
        if target.suffix.lower() not in SUPPORTED_SUFFIXES:
            answer = QMessageBox.question(
                self,
                "确认打开",
                "该文件不是 .epub 扩展名，仍要尝试打开吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self._loader is not None and self._loader.isRunning():
            self._loader.requestInterruption()
            self._loader.wait(1500)
        self._persist_progress()

        dialog = QProgressDialog("正在解析 EPUB…", "取消", 0, 8, self)
        dialog.setWindowTitle("打开书籍")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()

        loader = BookLoader(target, self)
        self._loader = loader
        loader.progress.connect(
            lambda done, total, message: (
                dialog.setLabelText(message),
                dialog.setMaximum(max(total, 8)),
                dialog.setValue(min(done, max(total, 8))),
            )
        )

        def on_loaded(book: EpubBook) -> None:
            dialog.reset()
            dialog.close()
            loader.deleteLater()
            self._loader = None
            self._apply_book(book)

        def on_failed(message: str) -> None:
            dialog.reset()
            dialog.close()
            loader.deleteLater()
            self._loader = None
            QMessageBox.critical(self, "无法打开", message)

        loader.loaded.connect(on_loaded)
        loader.failed.connect(on_failed)
        dialog.canceled.connect(self._cancel_loading)
        loader.start()

    def _cancel_loading(self) -> None:
        loader = self._loader
        if loader is None:
            return
        loader.requestInterruption()
        self._loader = None

    def _apply_book(self, book: EpubBook) -> None:
        self.close_book(silent=True)
        self.book = book
        self._book_key = book_cache_key(book.path)
        self.setWindowTitle(f"{book.describe()} — EPUB 阅读器")

        titles = [chapter.title for chapter in book.chapters]
        self.toc_panel.populate(book.toc, titles)

        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        for chapter in book.chapters:
            self.chapter_combo.addItem(f"{chapter.index + 1}. {chapter.title}", chapter.index)
        self.chapter_combo.blockSignals(False)

        self.status_label.setText(
            f"共 {book.chapter_count()} 个章节 · {book.describe()}"
        )
        self._remember_recent(book.path)
        self._update_actions()

        resume = self.progress_store.get_book(self._book_key)
        chapter = 0
        ratio = 0.0
        if resume:
            chapter = max(0, min(int(resume.get("chapter", 0)), book.chapter_count() - 1))
            ratio = float(resume.get("ratio", 0.0))
        self.goto_chapter(chapter, ratio=ratio)

    def close_book(self, silent: bool = False) -> None:
        self._persist_progress()
        if self._loader is not None and self._loader.isRunning():
            self._loader.requestInterruption()
        self.search_service.cancel()
        if self.book is not None:
            self.book.close()
        self.book = None
        self._book_key = None
        self._chapter = -1
        self._ratio = 0.0
        self._hits = []
        self._search_term = ""
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.clear()
        self.chapter_combo.blockSignals(False)
        self.toc_panel.tree.clear()
        self.search_panel.clear_results()
        self.reader.clear_highlights()
        self.reader.show_placeholder()
        self.position_label.setText("")
        self.status_label.setText("就绪")
        self.setWindowTitle("EPUB 阅读器")
        self._update_actions()
        if not silent:
            self.status_label.setText("已关闭当前书籍")

    # -- 章节导航 -----------------------------------------------------------

    def _chapter_count(self) -> int:
        return self.book.chapter_count() if self.book else 0

    def goto_chapter(
        self,
        index: int,
        anchor: str | None = None,
        ratio: float | None = None,
    ) -> None:
        if self.book is None:
            return
        total = self.book.chapter_count()
        if total == 0:
            return
        if index < 0:
            index = 0
        if index >= total:
            index = total - 1
        chapter = self.book.chapters[index]
        self._chapter = index
        self.reader.open_chapter(
            chapter,
            anchor=anchor,
            ratio=ratio,
            term=self._search_term,
            match_case=self.search_panel.case_box.isChecked(),
            whole_word=self.search_panel.word_box.isChecked(),
        )
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.setCurrentIndex(index)
        self.chapter_combo.blockSignals(False)
        self.toc_panel.set_current_chapter(index)
        self.status_label.setText(chapter.title)
        self._update_actions()
        self._update_position_label()

    def _on_combo_changed(self, index: int) -> None:
        if index >= 0 and index != self._chapter:
            self.goto_chapter(index)

    def _on_toc_activated(self, chapter: int, anchor: str) -> None:
        if chapter != self._chapter or anchor:
            self.goto_chapter(chapter, anchor=anchor or None)

    def _on_chapter_rendered(self, index: int) -> None:
        if self._search_term:
            self.reader.apply_highlights(
                self._search_term,
                self.search_panel.case_box.isChecked(),
                self.search_panel.word_box.isChecked(),
            )
        self._update_position_label()

    def _on_page_turn(self, forward: bool) -> None:
        if self.book is None:
            return
        self._persist_progress()
        target = self._chapter + (1 if forward else -1)
        if 0 <= target < self.book.chapter_count():
            self.goto_chapter(target, ratio=0.0 if forward else 1.0)

    def _on_nav_key(self, name: str, forward: bool) -> None:
        if name in ("pageleft", "pageup"):
            self.reader.scroll_page(False)
        elif name in ("pageright", "pagedown", "space"):
            self.reader.scroll_page(True)
        elif name == "lineup":
            self.reader.scroll_line(False)
        elif name == "linedown":
            self.reader.scroll_line(True)
        elif name == "home":
            self.goto_chapter(0, ratio=0.0)
        elif name == "end":
            self.goto_chapter(self._chapter_count() - 1, ratio=1.0)
        elif name == "findnext":
            self.show_search()
        elif name in ("nextchapter",):
            self.goto_chapter(self._chapter + 1)
        elif name in ("prevchapter",):
            self.goto_chapter(self._chapter - 1)

    def _on_scroll(self, ratio: float, at_end: bool) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self._update_position_label()
        self._save_timer.start()

    def _update_position_label(self) -> None:
        total = self._chapter_count()
        if total <= 0 or self.book is None:
            self.position_label.setText("")
            return
        percent = int(round(self._ratio * 100))
        self.position_label.setText(
            f"第 {self._chapter + 1}/{total} 章 · {percent}%"
        )
        self.status.setToolTip("")

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"字号 {self.reader.font_size} px")

    def change_font_size(self, delta: int) -> None:
        self.reader.set_style(font_size=self.reader.font_size + delta)
        self._update_zoom_label()

    def _persist_progress(self) -> None:
        if self.book is None or self._book_key is None or self._chapter < 0:
            return
        self.progress_store.set_book(self._book_key, self._chapter, self._ratio)
        self.progress_store.save()

    # -- 链接处理 -----------------------------------------------------------

    def _on_link(self, href: str) -> None:
        if self.book is None:
            return
        target = href.strip()
        if not target:
            return
        lowered = target.lower()
        if lowered.startswith(("http://", "https://", "mailto:")):
            QDesktopServices.openUrl(QUrl(target))
            return
        if lowered.startswith("file:"):
            url = QUrl(target)
            self._open_local_link(url)
            return
        path, _, fragment = target.partition("#")
        fragment = fragment or None
        if not path:
            if fragment:
                self.reader.scroll_to_id(fragment)
            return
        self._open_local_link(QUrl(path), fragment)

    def _open_local_link(self, url: QUrl, fragment: str | None = None) -> None:
        if self.book is None:
            return
        local = url.toLocalFile() or unquote_path(url.path())
        index = self.book.chapter_for_path(local)
        if index is None:
            self.status_label.setText("该链接指向书外资源，已忽略")
            return
        self.goto_chapter(index, anchor=fragment)

    # -- 搜索 ---------------------------------------------------------------

    def show_search(self) -> None:
        self.act_search_tab.setChecked(True)
        self.dock.show()
        self.tabs.setCurrentWidget(self.search_panel)
        self.search_panel.focus_entry()

    def search_selected_text(self, text: str) -> None:
        self.show_search()
        self.search_panel.set_query(text, trigger=True)

    def start_search(self, query: str, match_case: bool, whole_word: bool) -> None:
        if self.book is None:
            QMessageBox.information(self, "提示", "请先打开一本 EPUB 书籍。")
            return
        query = query.strip()
        if not query:
            return
        self._search_term = query
        self._hits = []
        self._hit_index = -1
        options = SearchOptions(
            query=query,
            match_case=match_case,
            whole_word=whole_word,
            limit=800,
        )
        self.search_panel.set_busy(True)
        token = self.search_service.start(self.book, options)
        if token is None:
            self.search_panel.set_busy(False)

    def _on_search_finished(self, _token: int, hits: list) -> None:
        self.search_panel.set_busy(False)
        self._hits = [hit for hit in hits if isinstance(hit, SearchHit)]
        self._hit_index = -1
        if self.book is None:
            return
        chapter_titles = [chapter.title for chapter in self.book.chapters]
        per_chapter: dict[int, int] = {}
        for hit in self._hits:
            per_chapter[hit.chapter] = (
                int(round(100 * hit.offset / max(1, len(self.book.chapters[hit.chapter].text))))
            )
        self.search_panel.show_results(self._hits, chapter_titles, per_chapter)
        if self._hits:
            self._open_hit(0)

    def _on_hit_activated(self, _chapter: int, row: int) -> None:
        self._hit_index = row
        self._open_hit(row)

    def _open_hit(self, row: int) -> None:
        if self.book is None or not (0 <= row < len(self._hits)):
            return
        hit = self._hits[row]
        chapter = self.book.chapters[hit.chapter]
        block_id, fraction = self._locate_block(chapter, hit.offset)
        self._chapter = hit.chapter
        self.reader.open_chapter(
            chapter,
            block=(block_id, fraction) if block_id else None,
            ratio=None if block_id else 0.0,
            term=self._search_term,
            match_case=self.search_panel.case_box.isChecked(),
            whole_word=self.search_panel.word_box.isChecked(),
        )
        self.chapter_combo.blockSignals(True)
        self.chapter_combo.setCurrentIndex(hit.chapter)
        self.chapter_combo.blockSignals(False)
        self.toc_panel.set_current_chapter(hit.chapter)
        self.status_label.setText(chapter.title)
        self._update_position_label()
        self._persist_progress()

    def _cycle_hit(self, direction: int) -> None:
        if not self._hits:
            self.show_search()
            return
        index = (self._hit_index + direction) % len(self._hits)
        self._hit_index = index
        self.search_panel.select_row(index)
        self._open_hit(index)

    def clear_search(self) -> None:
        self._search_term = ""
        self._hits = []
        self._hit_index = -1
        self.reader.clear_highlights()
        self.search_panel.clear_results()

    @staticmethod
    def _locate_block(chapter: Chapter, offset: int) -> tuple[str | None, float]:
        """根据正文偏移找到最近的块元素及块内相对位置。"""

        best: tuple[int, str] | None = None
        for position, block_id in chapter.blocks:
            if position <= offset:
                best = (position, block_id)
            else:
                break
        if best is None:
            return None, 0.0
        position, block_id = best
        block_text = chapter.block_texts.get(block_id, "")
        remainder = max(0, offset - position)
        fraction = 0.0
        if block_text:
            fraction = min(0.95, remainder / max(len(block_text), 1))
        return block_id, fraction

    # -- 其他 ---------------------------------------------------------------

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self,
            self.reader.theme,
            self.reader.font_size,
            self.reader.line_height,
            self.reader.max_width,
            self.reader.justify,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.reader.set_style(**values)
        action = self.theme_actions.get(values["theme"])
        if action is not None:
            action.setChecked(True)
        self._update_zoom_label()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 EPUB 阅读器",
            f"<h3>EPUB 阅读器 {__version__}</h3>"
            "<p>使用 Python + PyQt6 + QtWebEngine 构建的桌面 EPUB 阅读器。</p>"
            "<ul>"
            "<li>支持 EPUB 2 / EPUB 3（NCX 与 nav 目录）</li>"
            "<li>全书全文搜索、结果高亮与快速跳转</li>"
            "<li>章节目录导航、阅读进度记忆</li>"
            "<li>四种配色主题与字号、行距、版心调整</li>"
            "</ul>"
            f"<p style='color:gray'>数据目录：{app_data_dir()}</p>",
        )

    def show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "快捷键",
            "<table cellpadding='4'>"
            "<tr><td><b>Ctrl+O</b></td><td>打开 EPUB</td></tr>"
            "<tr><td><b>Ctrl+F</b></td><td>全文搜索</td></tr>"
            "<tr><td><b>F3 / Shift+F3</b></td><td>下一个 / 上一个匹配</td></tr>"
            "<tr><td><b>Esc</b></td><td>清除搜索高亮</td></tr>"
            "<tr><td><b>Ctrl+↑ / Ctrl+↓</b></td><td>上一章 / 下一章</td></tr>"
            "<tr><td><b>PageUp / PageDown / 空格</b></td><td>翻页（到边界自动换章）</td></tr>"
            "<tr><td><b>← / →</b></td><td>上一页 / 下一页</td></tr>"
            "<tr><td><b>Ctrl++ / Ctrl+- / Ctrl+0</b></td><td>放大 / 缩小 / 重置字号</td></tr>"
            "<tr><td><b>Ctrl+T</b></td><td>显示 / 隐藏侧边栏</td></tr>"
            "<tr><td><b>F11</b></td><td>全屏</td></tr>"
            "</table>",
        )

    def _update_actions(self) -> None:
        has_book = self.book is not None
        for action in (
            self.act_close,
            self.act_find,
            self.act_find_next,
            self.act_find_prev,
            self.act_prev_chapter,
            self.act_next_chapter,
            self.act_page_prev,
            self.act_page_next,
            self.act_home,
            self.act_end,
        ):
            action.setEnabled(has_book)
        self.chapter_combo.setEnabled(has_book)

    # -- 最近文件 -----------------------------------------------------------

    def _remember_recent(self, path: Path) -> None:
        recent = self.settings.value("recent/files", [])
        if isinstance(recent, str):
            recent = [recent]
        if not isinstance(recent, list):
            recent = []
        text = str(path)
        recent = [item for item in recent if item != text]
        recent.insert(0, text)
        self.settings.setValue("recent/files", recent[:12])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        menu = getattr(self, "recent_menu", None)
        if menu is None:
            return
        menu.clear()
        recent = self.settings.value("recent/files", [])
        if isinstance(recent, str):
            recent = [recent]
        if not isinstance(recent, list) or not recent:
            action = menu.addAction("（无）")
            action.setEnabled(False)
            return
        for item in recent:
            path = Path(str(item))
            label = path.name if path.name else str(item)
            action = menu.addAction(label)
            action.setToolTip(str(item))
            action.triggered.connect(lambda _checked=False, p=str(item): self.open_path(p))
        menu.addSeparator()
        clear = menu.addAction("清除最近记录")
        clear.triggered.connect(self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings.setValue("recent/files", [])
        self._refresh_recent_menu()

    # -- 拖放与关闭 ---------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(".epub"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".epub"):
                self.open_path(url.toLocalFile())
                break

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._persist_progress()
        self._remember_settings()
        self.search_service.cancel()
        if self.book is not None:
            self.book.close()
        super().closeEvent(event)


def unquote_path(path: str) -> str:
    from urllib.parse import unquote

    return unquote(path)
