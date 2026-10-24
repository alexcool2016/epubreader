"""GUI 自动化检查：加载示例书、切换主题、执行搜索并截图。

用法： python tools/gui_test.py [--shots]
生成图片位于 build_shots/ 目录。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from PyQt6 import QtWebEngineWidgets  # noqa: E402,F401  必须在 QApplication 之前导入

from epubreader.mainwindow import MainWindow  # noqa: E402
from tools.make_sample_epub import build  # noqa: E402

OUT = ROOT / "build_shots"


class Harness:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.window = MainWindow()
        self.window.resize(1280, 840)
        self.errors: list[str] = []
        self.shots = "--shots" in sys.argv
        self._finished = False

    def shot(self, name: str) -> None:
        if not self.shots:
            return
        OUT.mkdir(exist_ok=True)
        path = OUT / f"{name}.png"
        self.window.grab().save(str(path))
        print(f"截图：{path}", flush=True)

    def run(self) -> int:
        window = self.window
        window.show()

        sample = build(ROOT / "samples" / "sample.epub")

        def step_open() -> None:
            window.open_path(sample)

        def step_check_book() -> None:
            book = window.book
            if book is None:
                self.errors.append("书籍未加载")
                self.finish()
                return
            print(
                f"已加载: {book.title} / {book.chapter_count()} 章 / "
                f"{window.toc_panel.tree.topLevelItemCount()} 个一级目录项",
                flush=True,
            )
            if window.toc_panel.tree.topLevelItemCount() != 3:
                self.errors.append("目录项数量不正确")
            if window.chapter_combo.count() != 3:
                self.errors.append("章节下拉框数量不正确")
            if window._chapter != 0:
                self.errors.append(f"初始章节应为 0，实际 {window._chapter}")
            self.shot("01_light")

        def step_dark() -> None:
            window.reader.set_style(theme="dark")
            window.theme_actions["dark"].setChecked(True)

        def step_dark_check() -> None:
            self.shot("02_dark")
            window.reader.set_style(theme="light")

        def step_search() -> None:
            window.show_search()
            window.search_panel.set_query("灯塔")
            window.start_search("灯塔", False, False)

        def step_search_check() -> None:
            hits = window._hits
            print(
                f"搜索结果: {len(hits)} 条，面板行数 {window.search_panel.list.count()}",
                flush=True,
            )
            if len(hits) < 3:
                self.errors.append(f"搜索结果过少: {len(hits)}")
            if window.search_panel.list.count() != len(hits):
                self.errors.append("面板行数与结果数不一致")
            self.shot("03_search")

        def step_highlight_check() -> None:
            # 当前应停在第 0 章（搜索结果首条），该章含“灯塔”，应有高亮
            window.reader._run(
                "window.ER ? window.ER.markCount() : -1", self.on_mark_count
            )

        def step_chapter2() -> None:
            window.goto_chapter(1)
            window.reader.set_style(font_size=24)

        def step_chapter2_check() -> None:
            if window._chapter != 1:
                self.errors.append(f"切换章节失败，当前 {window._chapter}")
            self.shot("04_chapter2")

        def step_no_mark_check() -> None:
            # 第 1 章不含“灯塔”，高亮数应为 0
            window.reader._run(
                "window.ER ? window.ER.markCount() : -1", self.on_empty_mark_count
            )

        def step_zoom_reset() -> None:
            window.reader.set_style(font_size=19)

        def step_sepia() -> None:
            window.reader.set_style(theme="sepia", line_height=2.0)

        def step_sepia_check() -> None:
            self.shot("05_sepia")
            window.close_book(silent=True)
            window.reader.set_style(theme="light", line_height=1.75)

        def step_closed_check() -> None:
            if window.book is not None:
                self.errors.append("关闭书籍后 book 未清空")
            self.shot("06_closed")
            self.finish()

        schedule = [
            (900, step_open),
            (2800, step_check_book),
            (3300, step_dark),
            (4000, step_dark_check),
            (4500, step_search),
            (6200, step_search_check),
            (6600, step_highlight_check),
            (6900, step_chapter2),
            (7600, step_chapter2_check),
            (8000, step_no_mark_check),
            (8300, step_zoom_reset),
            (8700, step_sepia),
            (9300, step_sepia_check),
            (10100, step_closed_check),
        ]
        for delay, func in schedule:
            QTimer.singleShot(delay, lambda f=func: self.trace(f))

        # 兜底：超时未结束视为失败
        QTimer.singleShot(16000, self.finish)

        code = self.app.exec()
        if code:
            return code
        return 1 if self.errors else 0

    @staticmethod
    def trace(func) -> None:
        print(f">>> {func.__name__}", flush=True)
        try:
            func()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            print(f"步骤 {func.__name__} 异常: {exc}", flush=True)
            raise

    def on_mark_count(self, count: object) -> None:
        print(f"页内高亮数量: {count}", flush=True)
        if not isinstance(count, int) or count <= 0:
            self.errors.append(f"页内高亮失败: {count!r}")

    def on_empty_mark_count(self, count: object) -> None:
        print(f"第 1 章高亮数量（应为 0）: {count}", flush=True)
        if count != 0:
            self.errors.append(f"不该出现的页内高亮: {count!r}")

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self.errors:
            print("\n错误:", flush=True)
            for item in self.errors:
                print(f"  - {item}", flush=True)
        else:
            print("\nGUI 检查全部通过 ✅", flush=True)
        self.window.close()
        self.app.exit(1 if self.errors else 0)


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    harness = Harness(app)
    return harness.run()


if __name__ == "__main__":
    raise SystemExit(main())
