"""打包为 Windows 独立程序（PyInstaller，onedir 模式）。

用法：
    python build_exe.py               # 生成 dist/EpubReader/EpubReader.exe
    python build_exe.py --onefile     # 生成单个 exe（体积大、启动慢）
    python build_exe.py --zip         # 额外打包为 dist/EpubReader-<版本>-win64.zip
    python build_exe.py --no-prune    # 跳过体积裁剪（排查问题时用）

说明：
1. QtWebEngine 依赖大量 Chromium 资源（locales、icudtl.dat、QtWebEngineProcess.exe、
   resources.pak 等）。这些文件在 onefile 模式下每次启动都要解压到临时目录，
   既慢又容易被安全软件拦截，因此默认采用 onedir；分发时把整个目录压缩即可。
2. 不使用 --collect-all PyQt6（那会把 Qt 全家桶连同 QML/3D/Designer 一起塞进来）。
   依赖关系交给 PyInstaller 的 PyQt6 hook 自动分析，再对产物做一次白名单裁剪。
3. 裁剪后必须跑自检确认 WebEngine 仍能渲染：
       dist\\EpubReader\\EpubReader.exe --self-test
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from epubreader import __version__  # noqa: E402

APP_NAME = "EpubReader"
DISPLAY_NAME = "EPUB 阅读器"
ENTRY = ROOT / "main.py"
ICON = ROOT / "assets" / "app.ico"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

# 只保留中英文翻译，其余 200 多种语言（约 50 MB）删除
KEEP_TRANSLATIONS = {
    "qtbase_zh_CN.qm",
    "qtbase_zh_TW.qm",
    "qtbase_en.qm",
    "qt_zh_CN.qm",
    "qt_zh_TW.qm",
    "qt_en.qm",
    "qt_help_zh_CN.qm",
}

# 调试符号类资源，运行期用不到
DROP_SUFFIXES = (".debug.pak", ".debug.bin")

# 体积大且本项目确定用不到的 Qt 模块。
# 注意：Qt6Pdf / Qt6Multimedia / Qt6Quick / Qt6OpenGL / Qt6WebSockets 等
# 是 Qt6WebEngineCore 的隐式依赖，删除后会在导入阶段直接报
# “DLL load failed while importing QtWebEngineWidgets”，因此必须保留。
DROP_DLLS = (
    "Qt6Designer",          # Qt Designer 支持
    "Qt6UiTools",           # .ui 文件运行期加载
    "Qt6Quick3D",           # 3D 场景
    "Qt6Quick3DParticle",
    "Qt6QuickTimeline",     # QML 动画时间线
    "Qt6ShaderTools",       # 运行期着色器编译
    "Qt6VirtualKeyboard",   # 虚拟键盘
    "Qt6SpatialAudio",      # 空间音频
    "Qt6TextToSpeech",      # 语音合成
    "Qt6Sql",               # 数据库驱动
    "Qt6Test",              # 单元测试
    "Qt6Bluetooth",
    "Qt6Nfc",
    "Qt6SerialPort",
    "Qt6RemoteObjects",
    "Qt6Concurrent",
)

# 无关的插件目录（相对 Qt6/plugins）。
# multimedia / tls / networkinformation / platforms / imageformats 是 WebEngine 需要的，勿删。
DROP_PLUGIN_DIRS = (
    "assetimporters",
    "geometryloaders",
    "sceneparsers",
    "sqldrivers",
    "texttospeech",
    "qmllint",
    "qmlls",
    "renderers",
    "scxmldatamodel",
    "webview",
    "help",
)

# 无关的 QML 模块目录（相对 Qt6/qml）
DROP_QML_DIRS = (
    "QtQuick3D",
    "QtQuick3DPhysics",
    "QtQuick3DAssetUtils",
    "QtRemoteObjects",
    "QtSensors",
    "QtPositioning",
    "QtTest",
    "QtTextToSpeech",
    "QtMultimedia",
    "QtWebSockets",
    "QtQuick/Timeline",
    "QtQuick/Particles",
)

# WebEngine 必需的顶层目录/文件（裁剪时作为保护名单）
PROTECTED = {
    "QtWebEngineProcess.exe",
    "icudtl.dat",
    "qtwebengine_resources.pak",
    "qtwebengine_resources_100p.pak",
    "qtwebengine_resources_200p.pak",
    "v8_context_snapshot.bin",
}


def _extra_datas() -> list[str]:
    datas: list[str] = []
    if ICON.exists():
        datas.append(f"{ICON};assets")
    png = ICON.with_suffix(".png")
    if png.exists():
        datas.append(f"{png};assets")

    # 示例书籍一并放入，方便第一次运行直接体验
    sample = ROOT / "samples" / "sample.epub"
    if sample.exists():
        datas.append(f"{sample};samples")

    readme = ROOT / "README.md"
    if readme.exists():
        datas.append(f"{readme};.")

    return datas


def _version_file() -> Path:
    path = BUILD / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = (__version__.split(".") + ["0", "0", "0", "0"])[:4]
    nums = ", ".join(str(int(p)) if p.isdigit() else "0" for p in parts)
    path.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({nums}),
    prodvers=({nums}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', 'EpubReader'),
         StringStruct('FileDescription', '{DISPLAY_NAME}'),
         StringStruct('FileVersion', '{__version__}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', 'MIT License'),
         StringStruct('OriginalFilename', '{APP_NAME}.exe'),
         StringStruct('ProductName', '{DISPLAY_NAME}'),
         StringStruct('ProductVersion', '{__version__}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return path


def _hidden_imports() -> list[str]:
    return [
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebChannel",
        "PyQt6.QtPrintSupport",
    ]


def build(onefile: bool = False, console: bool = False, clean: bool = True) -> Path:
    if clean:
        for target in (DIST, BUILD):
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed" if not console else "--console",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON),
        "--version-file",
        str(_version_file()),
        # 本项目不使用这些重量级模块
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "unittest",
        "--exclude-module",
        "pydoc",
        "--exclude-module",
        "PyQt6.QtBluetooth",
        "--exclude-module",
        "PyQt6.QtDesigner",
        "--exclude-module",
        "PyQt6.QtNfc",
        "--exclude-module",
        "PyQt6.QtPositioning",
        "--exclude-module",
        "PyQt6.QtQml",
        "--exclude-module",
        "PyQt6.QtQuick",
        "--exclude-module",
        "PyQt6.QtQuick3D",
        "--exclude-module",
        "PyQt6.QtQuickWidgets",
        "--exclude-module",
        "PyQt6.QtRemoteObjects",
        "--exclude-module",
        "PyQt6.QtSensors",
        "--exclude-module",
        "PyQt6.QtSerialPort",
        "--exclude-module",
        "PyQt6.QtSql",
        "--exclude-module",
        "PyQt6.QtTest",
        "--exclude-module",
        "PyQt6.QtTextToSpeech",
    ]
    for module in _hidden_imports():
        cmd.extend(["--hidden-import", module])
    if onefile:
        cmd.append("--onefile")
    for entry in _extra_datas():
        cmd.extend(["--add-data", entry])
    cmd.append(str(ENTRY))

    print("执行：", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller 失败，退出码 {result.returncode}")

    return DIST / f"{APP_NAME}.exe" if onefile else DIST / APP_NAME / f"{APP_NAME}.exe"


def _dir_size(path: Path) -> tuple[int, int]:
    total = 0
    count = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
            count += 1
    return total, count


def prune(app_dir: Path) -> int:
    """删除运行期用不到的 Qt 资源，返回释放的字节数。"""

    root = app_dir / "_internal"
    if not root.is_dir():
        root = app_dir

    before, _ = _dir_size(app_dir)
    removed: list[str] = []

    # 1. 翻译文件
    trans = root / "PyQt6" / "Qt6" / "translations"
    if trans.is_dir():
        for item in trans.iterdir():
            if item.is_file() and item.name not in KEEP_TRANSLATIONS:
                item.unlink(missing_ok=True)
                removed.append(item.name)

    # 2. 调试资源
    for item in root.rglob("*.debug.pak"):
        item.unlink(missing_ok=True)
        removed.append(item.name)
    for item in root.rglob("*.debug.bin"):
        item.unlink(missing_ok=True)
        removed.append(item.name)

    # 3. devtools 资源（仅开发者工具需要，约 83 MB）
    for item in root.rglob("qtwebengine_devtools_resources*.pak"):
        item.unlink(missing_ok=True)
        removed.append(item.name)

    # 4. 用不到的 Qt DLL
    qt_bin = root / "PyQt6" / "Qt6" / "bin"
    if qt_bin.is_dir():
        for item in qt_bin.glob("Qt6*.dll"):
            if any(item.stem.startswith(name) for name in DROP_DLLS):
                item.unlink(missing_ok=True)
                removed.append(item.name)

    # 5. 插件目录
    plugins = root / "PyQt6" / "Qt6" / "plugins"
    for name in DROP_PLUGIN_DIRS:
        target = plugins / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(f"plugins/{name}")

    # 6. QML 模块目录
    qml = root / "PyQt6" / "Qt6" / "qml"
    for name in DROP_QML_DIRS:
        target = qml / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(f"qml/{name}")

    after, _ = _dir_size(app_dir)
    freed = max(0, before - after)
    print(f"\n裁剪完成：删除 {len(removed)} 项，释放 {freed / 1024 / 1024:.1f} MB")
    return freed


def make_zip(app_dir: Path) -> Path:
    archive = DIST / f"{APP_NAME}-{__version__}-win64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item in sorted(app_dir.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(app_dir.parent))
    return archive


def main() -> int:
    onefile = "--onefile" in sys.argv
    want_zip = "--zip" in sys.argv
    console = "--console" in sys.argv
    do_prune = "--no-prune" not in sys.argv

    if not ICON.exists():
        print("未找到图标，先生成 assets/app.ico …", flush=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")], check=True)

    exe = build(onefile=onefile, console=console)
    if not exe.exists():
        raise SystemExit("打包结束但未找到输出文件")

    if do_prune and not onefile:
        prune(exe.parent)

    size, count = _dir_size(exe.parent)
    print(f"\n输出：{exe}")
    print(f"文件数：{count}，总体积：{size / 1024 / 1024:.1f} MB")

    if want_zip and not onefile:
        archive = make_zip(exe.parent)
        print(f"压缩包：{archive}（{archive.stat().st_size / 1024 / 1024:.1f} MB）")

    print("\n下一步：执行自检确认渲染正常")
    print(f"  {exe} --self-test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
