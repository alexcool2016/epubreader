"""程序入口：初始化 QtWebEngine 环境并启动主窗口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_ID = "EpubReader.App.1"


def _configure_environment() -> None:
    """在导入 QtWebEngine 之前设置必要的环境变量。"""

    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-driver-bug-workarounds")
    if os.name == "nt":
        # 高 DPI 缩放交给 Qt 处理
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        # 让任务栏使用本程序图标，而不是 python.exe 的图标
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_environment()

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    # QtWebEngine 必须在创建 QApplication 之前导入，
    # 否则会因缺少共享 OpenGL 上下文而直接崩溃。
    from PyQt6 import QtWebEngineWidgets  # noqa: F401
    from .mainwindow import MainWindow

    args = list(sys.argv if argv is None else argv)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(args)
    app.setApplicationName("EpubReader")
    app.setApplicationDisplayName("EPUB 阅读器")
    app.setOrganizationName("EpubReader")
    app.setStyle("Fusion")

    from .mainwindow import app_icon

    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    candidates = [item for item in args[1:] if not item.startswith("-")]
    startup = None
    if candidates:
        candidate = Path(candidates[0])
        if candidate.exists():
            startup = str(candidate)

    # 打包后没有控制台，用自检模式验证渲染链路是否完整
    if "--self-test" in args:
        from .selftest import run_self_test

        return run_self_test(Path(startup) if startup else None)

    window = MainWindow(startup)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
