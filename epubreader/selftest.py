"""内置自检：在打包后的程序里跑一遍“解析 → 搜索 → 渲染 → 高亮”链路。

用法（QApplication 已创建之后调用）：
    EpubReader.exe --self-test samples\\sample.epub

结果逐行写入报告文件，退出码 0 表示全部通过。
之所以需要它，是因为 --windowed 打包后没有控制台输出，
只能靠退出码与报告文件判断 WebEngine 资源是否齐备。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

TIMEOUT_MS = 25000
REPORT_NAME = "selftest_report.txt"


class _Reporter:
    """把每一步立刻落盘，进程若卡住也能看到停在哪儿。"""

    def __init__(self) -> None:
        self.path = Path.cwd() / REPORT_NAME
        self.ok = True
        try:
            self.path.write_text("", encoding="utf-8")
        except OSError:
            import tempfile

            self.path = Path(tempfile.gettempdir()) / REPORT_NAME
            self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        print(message, flush=True)
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        except OSError:
            pass

    def fail(self, message: str) -> None:
        self.ok = False
        self.log(f"FAIL: {message}")


def run_self_test(epub_path: Path | None) -> int:
    import platform

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from . import __version__
    from .paths import bundle_dir, resource_path

    report = _Reporter()
    log = report.log

    log(f"EpubReader {__version__} self-test")
    log(f"frozen={getattr(sys, 'frozen', False)} python={platform.python_version()}")
    log(f"executable={sys.executable}")
    log(f"bundle_dir={bundle_dir()}")
    log(f"meipass={getattr(sys, '_MEIPASS', None)}")
    icon = resource_path("assets", "app.ico")
    log(f"icon exists={icon.exists()} -> {icon}")

    if epub_path is None:
        epub_path = resource_path("samples", "sample.epub")
    log(f"epub exists={epub_path.exists()} -> {epub_path}")

    # --- 1. 解析 ---
    try:
        from .book import EpubBook

        book = EpubBook.open(epub_path)
        log(f"parsed title={book.title!r} author={book.author!r} chapters={book.chapter_count()}")
        if book.chapter_count() != 3:
            report.fail(f"章节数异常：{book.chapter_count()}")
    except Exception:  # noqa: BLE001
        report.fail("解析异常:\n" + traceback.format_exc())
        log("result=FAIL")
        return 1

    # --- 2. 搜索 ---
    try:
        from .search import SearchOptions, search_book

        hits = search_book(book, SearchOptions(query="灯塔", limit=50))
        log(f"search hits={len(hits)}")
        if hits:
            log(f"first snippet={hits[0].snippet}")
        if len(hits) < 3:
            report.fail(f"搜索结果过少：{len(hits)}")
    except Exception:  # noqa: BLE001
        report.fail("搜索异常:\n" + traceback.format_exc())

    # --- 3. 渲染 + 高亮（需要事件循环）---
    app = QApplication.instance()
    if app is None:
        report.fail("QApplication 未创建")
        log("result=FAIL")
        return 1

    from .reader import ReaderView

    log("creating ReaderView")
    view = ReaderView()
    view.set_style(theme="light")
    view.resize(900, 640)
    view.show()
    log("ReaderView ready")

    state = {"done": False}

    def on_rendered(index: int) -> None:
        log(f"chapter_rendered={index}")

        def after_highlight(count: object) -> None:
            log(f"mark_count={count}")
            if not isinstance(count, int) or count <= 0:
                report.fail(f"页内高亮为 {count!r}")
            done()

        view._run("window.ER ? window.ER.markCount() : -1", after_highlight)

    def done() -> None:
        if state["done"]:
            return
        state["done"] = True
        log(f"result={'PASS' if report.ok else 'FAIL'}")
        view.close()
        app.quit()

    def on_timeout() -> None:
        if state["done"]:
            return
        report.fail("渲染超时：WebEngine 未在限定时间内完成加载")
        done()

    view.chapter_rendered.connect(on_rendered)
    log("opening chapter 0")
    view.open_chapter(book.chapters[0], term="灯塔")
    QTimer.singleShot(TIMEOUT_MS, on_timeout)
    app.exec()
    return 0 if report.ok else 1
