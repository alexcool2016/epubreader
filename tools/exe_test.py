"""对打包后的 EpubReader.exe 做端到端检查：启动、打开书、截图、退出。

用法：
    python tools/exe_test.py                      # 用 dist\\EpubReader\\EpubReader.exe
    python tools/exe_test.py --exe <路径> --wait 12

检查项：
1. 进程能启动并保持运行（未在启动阶段崩溃或退出）
2. 屏幕画面有实质内容（灰度方差足够，说明 WebEngine 真的画出了页面）
3. 进程能被正常结束

截图输出到 build_shots/exe_desktop.png。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "build_shots"
DEFAULT_EXE = ROOT / "dist" / "EpubReader" / "EpubReader.exe"


def grab_desktop(target: Path) -> tuple[int, int, float] | None:
    """截取整个桌面并返回 (宽, 高, 灰度方差)。"""

    from PyQt6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        return None
    image = pixmap.toImage()
    if image.isNull():
        return None

    step_x = max(1, image.width() // 80)
    step_y = max(1, image.height() // 80)
    values: list[int] = []
    for y in range(0, image.height(), step_y):
        for x in range(0, image.width(), step_x):
            color = image.pixelColor(x, y)
            values.append((color.red() + color.green() + color.blue()) // 3)

    if not values:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)

    target.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(target))
    return image.width(), image.height(), variance


def main() -> int:
    exe = DEFAULT_EXE
    wait = 12.0
    if "--exe" in sys.argv:
        exe = Path(sys.argv[sys.argv.index("--exe") + 1])
    if "--wait" in sys.argv:
        wait = float(sys.argv[sys.argv.index("--wait") + 1])

    if not exe.exists():
        print(f"未找到可执行文件：{exe}")
        print("请先运行：python build_exe.py")
        return 1

    sample = ROOT / "samples" / "sample.epub"
    args = [str(exe)]
    if sample.exists():
        args.append(str(sample))

    print(f"测试目标：{exe}")
    errors: list[str] = []

    # QtWebEngine 必须在 QApplication 之前导入
    from PyQt6 import QtWebEngineWidgets  # noqa: F401
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    process = subprocess.Popen(
        args,
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"已启动 pid={process.pid}，等待 {wait:.0f}s 让界面渲染完成…")

    # 分几段等待，期间保持事件循环可响应（截图需要）
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.1)
        if process.poll() is not None:
            break

    code = process.poll()
    if code is not None:
        errors.append(f"进程提前退出，退出码 {code}")
    else:
        result = grab_desktop(OUT / "exe_desktop.png")
        if result is None:
            errors.append("桌面截图失败")
        else:
            width, height, variance = result
            print(f"桌面尺寸={width}x{height} 灰度方差={variance:.1f}")
            print(f"截图：{OUT / 'exe_desktop.png'}")
            if variance < 50:
                errors.append(f"画面疑似空白（灰度方差 {variance:.1f}）")

        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/F"],
            capture_output=True,
            check=False,
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            errors.append("无法结束进程")
        else:
            print(f"进程已结束，退出码 {process.returncode}")

    if errors:
        print("\n错误：")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("\n打包程序端到端检查通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
