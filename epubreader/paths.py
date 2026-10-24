"""应用数据目录、缓存目录与简单的 JSON 持久化工具。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import sys
from pathlib import Path
from typing import Any

APP_NAME = "EpubReader"


def bundle_dir() -> Path:
    """打包后可执行文件所在目录；源码运行时为项目根目录。"""

    frozen = getattr(sys, "frozen", False)
    if frozen:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """定位随程序分发的静态资源（兼容 PyInstaller 的 _MEIPASS 临时目录）。"""

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass).joinpath(*parts)
        if candidate.exists():
            return candidate
    return bundle_dir().joinpath(*parts)


def app_data_dir() -> Path:
    """返回应用数据目录（Windows 下为 %LOCALAPPDATA%\\EpubReader）。"""

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_root() -> Path:
    """EPUB 解压缓存根目录。"""

    path = app_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def book_cache_key(epub_path: str | os.PathLike[str]) -> str:
    """根据文件路径、大小与修改时间生成稳定的缓存键。"""

    path = Path(epub_path)
    try:
        stat = path.stat()
        stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        stamp = "0"
    raw = f"{path.resolve()}|{stamp}"
    return hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()[:24]


class JsonStore:
    """写入时使用临时文件 + 原子替换，避免半截 JSON。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                self._data = data
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".tmp-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=1)
            os.replace(temp_name, self.path)
        except OSError:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


class ProgressStore(JsonStore):
    """保存每本书的阅读进度（章节 + 章节内滚动比例）。"""

    def __init__(self) -> None:
        super().__init__(app_data_dir() / "progress.json")

    def get_book(self, key: str) -> dict[str, Any] | None:
        books = self.get("books", {})
        if not isinstance(books, dict):
            return None
        value = books.get(key)
        return value if isinstance(value, dict) else None

    def set_book(self, key: str, chapter: int, ratio: float) -> None:
        books = self.get("books", {})
        if not isinstance(books, dict):
            books = {}
        books[key] = {"chapter": int(chapter), "ratio": float(ratio)}
        self.set("books", books)
