"""EPUB 解析：元数据、书脊、目录、章节 HTML 预处理与全文文本提取。

本模块不依赖 Qt，可单独用于命令行测试。
"""

from __future__ import annotations

import html as html_lib
import posixpath
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote, unquote
from xml.etree import ElementTree as ET

from .paths import book_cache_key, cache_root


class EpubError(Exception):
    """EPUB 结构错误（缺文件、XML 损坏等）。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Chapter:
    """一个阅读单元（spine 中的一份 XHTML 文档）。"""

    index: int
    path: str  # 压缩包内路径
    title: str
    file: Path  # 预处理后写到磁盘的 HTML 文件
    text: str  # 正文纯文本（块之间以换行分隔）
    blocks: list[tuple[int, str]]  # (正文偏移, 最近块元素 id)
    block_texts: dict[str, str]  # 块 id -> 规范化文本
    headings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TocEntry:
    """目录项，按先序展开，level 从 1 开始。"""

    title: str
    level: int
    chapter: int | None = None
    anchor: str | None = None
    href: str = ""


# ---------------------------------------------------------------------------
# HTML 预处理：去脚本、收集文本、给块元素补 id
# ---------------------------------------------------------------------------

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

_SKIP = {"script", "noscript", "iframe", "frame", "object", "embed", "applet"}

_BLOCK = {
    "address", "article", "aside", "blockquote", "body", "center", "dd", "div",
    "dl", "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul", "caption",
}

_KEEP_ATTR = {
    "id", "class", "style", "href", "src", "alt", "title", "width", "height",
    "colspan", "rowspan", "align", "valign", "lang", "dir", "role", "start",
    "type", "value", "reversed", "span", "datetime", "cite", "name", "size",
    "color", "face", "border", "cellpadding", "cellspacing", "nowrap",
    "axis", "headers", "scope", "abbr", "summary",
}


class _TextBuilder:
    """增量构建规范化文本，并记录长度，供块偏移使用。"""

    __slots__ = ("_parts", "length", "_last")

    def __init__(self) -> None:
        self._parts: list[str] = []
        self.length = 0
        self._last = ""

    def add(self, raw: str) -> None:
        if not raw:
            return
        text = re.sub(r"\s+", " ", raw)
        if not text:
            return
        if text[0] == " " and (self.length == 0 or self._last in (" ", "\n")):
            text = text[1:]
            if not text:
                return
        self._parts.append(text)
        self.length += len(text)
        self._last = text[-1]

    def marker(self, mark: str) -> None:
        if self.length == 0 or self._last == mark:
            return
        self._parts.append(mark)
        self.length += 1
        self._last = mark

    def value(self) -> str:
        return "".join(self._parts).strip()


class _ContentParser(HTMLParser):
    """把 EPUB 的 XHTML 转成安全的、可定位的 HTML 片段。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.head_parts: list[str] = []
        self.body_parts: list[str] = []
        self.text = _TextBuilder()
        self.blocks: list[tuple[int, str]] = []
        self.block_texts: dict[str, str] = {}
        self.headings: list[str] = []
        self._chunks: dict[str, list[str]] = {}
        self._block_tag: dict[str, str] = {}
        self._stack: list[list] = []  # [tag, block_id]
        self._where = "body"
        self._skip = 0
        self._seq = 0

    # -- 输出 ---------------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._where == "head":
            self.head_parts.append(text)
        else:
            self.body_parts.append(text)

    def _render_attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        out = []
        for key, value in attrs:
            if not key:
                continue
            key = key.lower()
            if key.startswith("on"):
                continue
            value = "" if value is None else value
            if key in ("href", "src"):
                lowered = value.strip().lower()
                if lowered.startswith(("javascript:", "vbscript:")):
                    continue
            if key not in _KEEP_ATTR and not key.startswith("data-") and not key.startswith("aria-"):
                continue
            out.append(f' {key}="{html_lib.escape(value, quote=True)}"')
        return "".join(out)

    def _assign_block(self, attrs: list[tuple[str, str | None]], tag: str) -> str:
        existing = ""
        index = -1
        for pos, (key, value) in enumerate(attrs):
            if key and key.lower() == "id" and value:
                existing = value
                index = pos
                break
        if existing and existing not in self._chunks:
            block_id = existing
        else:
            self._seq += 1
            block_id = f"erb{self._seq}"
            if index >= 0:
                attrs[index] = ("id", block_id)
            else:
                attrs.append(("id", block_id))
        self._chunks[block_id] = []
        self._block_tag[block_id] = tag
        return block_id

    def _push_text(self, text: str) -> None:
        if self._where != "body":
            return
        self.text.add(text)
        for _tag, block_id in self._stack:
            if block_id:
                chunks = self._chunks.get(block_id)
                if chunks is not None:
                    chunks.append(text)

    def _close_block(self, block_id: str, tag: str) -> None:
        chunks = self._chunks.pop(block_id, None)
        if chunks is None:
            return
        plain = re.sub(r"\s+", " ", "".join(chunks)).strip()
        if plain:
            self.block_texts[block_id] = plain
            if tag in ("h1", "h2", "h3") and len(self.headings) < 5:
                self.headings.append(plain[:150])
        self.text.marker("\n")

    # -- HTMLParser 回调 ----------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        tag = tag.lower()
        if self._skip:
            if tag in _SKIP:
                self._skip += 1
            return
        if tag in _SKIP:
            self._skip = 1
            return
        if tag == "html":
            return
        if tag == "head":
            self._where = "head"
            return
        if tag == "body":
            self._where = "body"
            return

        items = list(attrs)
        if tag == "br":
            self.text.marker("\n")
            self._emit("<br>")
            return

        block_id = None
        if tag in _BLOCK:
            self.text.marker("\n")
            block_id = self._assign_block(items, tag)
            self.blocks.append((self.text.length, block_id))

        rendered = self._render_attrs(items)
        self._emit(f"<{tag}{rendered}>")

        if tag in _VOID:
            if tag in _BLOCK:
                self.text.marker("\n")
            return
        self._stack.append([tag, block_id])

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[override]
        tag = tag.lower()
        if self._skip:
            return
        if tag in _SKIP:
            return
        if tag in ("html", "head", "body"):
            return
        if tag == "br":
            self.text.marker("\n")
            self._emit("<br>")
            return
        items = list(attrs)
        block_id = None
        if tag in _BLOCK:
            self.text.marker("\n")
            block_id = self._assign_block(items, tag)
            self.blocks.append((self.text.length, block_id))
        rendered = self._render_attrs(items)
        self._emit(f"<{tag}{rendered}/>")
        if block_id:
            self._close_block(block_id, tag)

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        tag = tag.lower()
        if self._skip:
            if tag in _SKIP:
                self._skip -= 1
            return
        if tag in _SKIP:
            return
        if tag == "head":
            self._where = "body"
            return
        if tag in ("html", "body"):
            return
        if tag in _VOID:
            return

        index = None
        for pos in range(len(self._stack) - 1, -1, -1):
            if self._stack[pos][0] == tag:
                index = pos
                break
        if index is None:
            return
        while len(self._stack) > index:
            popped_tag, block_id = self._stack.pop()
            if block_id:
                self._close_block(block_id, popped_tag)
        self._emit(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip or not data:
            return
        self._emit(html_lib.escape(data, quote=False))
        self._push_text(data)

    def handle_entityref(self, name: str) -> None:
        if self._skip:
            return
        raw = f"&{name};"
        self._emit(raw)
        self._push_text(html_lib.unescape(raw))

    def handle_charref(self, name: str) -> None:
        if self._skip:
            return
        raw = f"&#{name};"
        self._emit(raw)
        self._push_text(html_lib.unescape(raw))

    def close(self) -> None:
        super().close()
        while self._stack:
            tag, block_id = self._stack.pop()
            if block_id:
                self._close_block(block_id, tag)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(elem: ET.Element | None, name: str) -> list[ET.Element]:
    if elem is None:
        return []
    return [child for child in elem if _local(child.tag) == name]


def _first(elem: ET.Element | None, name: str) -> ET.Element | None:
    for child in _children(elem, name):
        return child
    return None


def _descendants(elem: ET.Element | None, name: str) -> list[ET.Element]:
    if elem is None:
        return []
    return [node for node in elem.iter() if _local(node.tag) == name]


def _text_of(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return re.sub(r"\s+", " ", "".join(elem.itertext())).strip()


def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", "replace")
    declared = None
    match = re.search(rb"<\?xml[^>]*encoding\s*=\s*[\"']([\w\-]+)[\"']", raw[:500])
    if match:
        declared = match.group(1).decode("ascii", "ignore")
    else:
        match = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([\w\-]+)", raw[:3000], re.I)
        if match:
            declared = match.group(1).decode("ascii", "ignore")
    for candidate in (declared, "utf-8", "gb18030", "big5", "latin-1"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def _norm_path(name: str) -> str:
    name = unquote(name.replace("\\", "/")).lstrip("/")
    return posixpath.normpath(name)


class _ManifestItem:
    __slots__ = ("item_id", "path", "media_type", "properties")

    def __init__(self, item_id: str, path: str, media_type: str, properties: str) -> None:
        self.item_id = item_id
        self.path = path
        self.media_type = media_type.lower()
        self.properties = properties.lower()

    @property
    def is_html(self) -> bool:
        if self.media_type in (
            "application/xhtml+xml",
            "text/html",
            "application/html",
            "text/x-oeb1-document",
        ):
            return True
        suffix = posixpath.splitext(self.path)[1].lower()
        return suffix in (".xhtml", ".html", ".htm", ".xht")


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------


class EpubBook:
    """打开并预处理一本 EPUB。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.title = self.path.stem
        self.author = ""
        self.language = ""
        self.chapters: list[Chapter] = []
        self.toc: list[TocEntry] = []
        self.content_dir: Path | None = None
        self._zip: zipfile.ZipFile | None = None
        self._names: dict[str, str] = {}
        self._by_path: dict[str, int] = {}
        self._prepared_dir: Path | None = None

    # -- 打开 ---------------------------------------------------------------

    @classmethod
    def open(
        cls,
        path: str | Path,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> "EpubBook":
        book = cls(path)
        book._open(progress or (lambda done, total, message: None))
        return book

    def _report(self, progress: Callable[[int, int, str], None], done: int, total: int, msg: str) -> None:
        progress(done, max(total, 1), msg)

    def _open(self, progress: Callable[[int, int, str], None]) -> None:
        try:
            self._zip = zipfile.ZipFile(self.path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise EpubError(f"无法打开文件：{exc}") from exc

        for info in self._zip.infolist():
            if info.is_dir():
                continue
            self._names[info.filename.replace("\\", "/").lower()] = info.filename

        progress(1, 8, "读取容器信息…")
        opf_path = self._find_opf()
        opf_base = posixpath.dirname(opf_path)
        opf_root = self._parse_xml(opf_path, "OPF 内容文件")

        self._read_metadata(opf_root)

        progress(2, 8, "解析清单与书脊…")
        manifest = self._parse_manifest(opf_root, opf_base)
        spine = self._parse_spine(opf_root, manifest)

        progress(3, 8, "解压资源文件…")
        self._extract()

        progress(4, 8, "预处理章节内容…")
        total = len(spine)
        chapters: list[Chapter] = []
        for position, item in enumerate(spine):
            chapter = self._prepare_chapter(opf_base, item, len(chapters))
            if chapter is not None:
                chapters.append(chapter)
            self._report(progress, 4 + int(3 * (position + 1) / max(total, 1)), 8,
                         f"预处理章节 {position + 1}/{total}…")
        self.chapters = chapters

        progress(7, 8, "解析目录…")
        self.toc = self._parse_toc(opf_root, manifest, opf_base)

        self._assign_titles()
        self._index_paths()
        self._load_ncx_titles_fallback()
        progress(8, 8, "完成")

    def close(self) -> None:
        if self._zip is not None:
            try:
                self._zip.close()
            finally:
                self._zip = None

    # -- 元数据 -------------------------------------------------------------

    def _read_metadata(self, opf_root: ET.Element) -> None:
        metadata = _first(opf_root, "metadata")
        title = _text_of(_first(metadata, "title"))
        if title:
            self.title = title
        creators = _children(metadata, "creator")
        self.author = "、".join(t for t in (_text_of(c) for c in creators) if t)
        self.language = _text_of(_first(metadata, "language"))

    def _find_opf(self) -> str:
        try:
            raw = self._read("META-INF/container.xml")
            root = ET.fromstring(raw)
            for rootfile in _descendants(root, "rootfile"):
                media = (rootfile.get("media-type") or "").lower()
                full_path = rootfile.get("full-path")
                if full_path and (not media or media == "application/oebps-package+xml"):
                    return _norm_path(full_path)
        except (EpubError, ET.ParseError):
            pass
        for name in self._names.values():
            if name.lower().endswith(".opf") and not name.lower().startswith("meta-inf"):
                return _norm_path(name)
        raise EpubError("未找到 OPF 内容文件，可能不是有效的 EPUB。")

    # -- 清单 / 书脊 --------------------------------------------------------

    def _parse_manifest(self, opf_root: ET.Element, opf_base: str) -> dict[str, _ManifestItem]:
        manifest: dict[str, _ManifestItem] = {}
        for item in _descendants(_first(opf_root, "manifest"), "item"):
            item_id = item.get("id") or ""
            href = item.get("href") or ""
            if not item_id or not href:
                continue
            manifest[item_id] = _ManifestItem(
                item_id,
                self._resolve(opf_base, href),
                item.get("media-type") or "",
                item.get("properties") or "",
            )
        return manifest

    def _parse_spine(self, opf_root: ET.Element, manifest: dict[str, _ManifestItem]) -> list[_ManifestItem]:
        spine_elem = _first(opf_root, "spine")
        ordered: list[_ManifestItem] = []
        seen: set[str] = set()
        for ref in _children(spine_elem, "itemref"):
            item = manifest.get(ref.get("idref") or "")
            if item is None or not item.is_html:
                continue
            if item.path in seen:
                continue
            seen.add(item.path)
            ordered.append(item)
        if not ordered:
            ordered = [item for item in manifest.values() if item.is_html]
            ordered.sort(key=lambda entry: entry.path)
        if not ordered:
            raise EpubError("这本书没有可显示的正文内容。")
        return ordered

    # -- 解压 ---------------------------------------------------------------

    def _extract(self) -> None:
        key = book_cache_key(self.path)
        root = cache_root() / key
        marker = root / ".complete"
        content = root / "content"
        if not marker.exists():
            shutil.rmtree(root, ignore_errors=True)
            content.mkdir(parents=True, exist_ok=True)
            assert self._zip is not None
            for info in self._zip.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if name.startswith("__MACOSX/"):
                    continue
                parts = [p for p in name.split("/") if p not in ("", ".", "..")]
                if not parts:
                    continue
                target = content.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with self._zip.open(info) as source, open(target, "wb") as dest:
                        shutil.copyfileobj(source, dest)
                except (OSError, zipfile.BadZipFile):
                    continue
            marker.write_text("ok", encoding="utf-8")
        self.content_dir = content
        self._prepared_dir = root / "prepared"
        shutil.rmtree(self._prepared_dir, ignore_errors=True)
        self._prepared_dir.mkdir(parents=True, exist_ok=True)

    def _content_path(self, zip_path: str) -> Path:
        assert self.content_dir is not None
        parts = [p for p in zip_path.split("/") if p not in ("", ".", "..")]
        return self.content_dir.joinpath(*parts)

    # -- 章节预处理 ---------------------------------------------------------

    def _prepare_chapter(self, opf_base: str, item: _ManifestItem, index: int) -> Chapter | None:
        try:
            raw = self._read(item.path)
        except EpubError:
            return None
        text = _decode(raw)
        parser = _ContentParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception:  # 某些 EPUB 的 HTML 极不规范，尽量保留已解析部分
            pass

        source_file = self._content_path(item.path)
        try:
            base_url = source_file.resolve().as_uri()
        except ValueError:
            base_url = "about:blank"

        assert self._prepared_dir is not None
        prepared = self._prepared_dir / f"{index:04d}.html"
        document = (
            "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
            f"<base href=\"{html_lib.escape(base_url, quote=True)}\">\n"
            + "".join(parser.head_parts)
            + "\n</head>\n<body>\n"
            + "".join(parser.body_parts)
            + "\n</body>\n</html>\n"
        )
        prepared.write_text(document, encoding="utf-8")

        name = posixpath.basename(item.path)
        heading = parser.headings[0][:80] if parser.headings else ""
        return Chapter(
            index=index,
            path=item.path,
            title=heading or Path(name).stem,
            file=prepared,
            text=parser.text.value(),
            blocks=parser.blocks,
            block_texts=parser.block_texts,
            headings=parser.headings,
        )

    # -- 目录 ---------------------------------------------------------------

    def _parse_toc(
        self,
        opf_root: ET.Element,
        manifest: dict[str, _ManifestItem],
        opf_base: str,
    ) -> list[TocEntry]:
        nav_item = None
        for item in manifest.values():
            if "nav" in item.properties.split():
                nav_item = item
                break
        if nav_item is not None:
            entries = self._parse_nav_document(nav_item.path)
            if entries:
                self._resolve_entries(entries, posixpath.dirname(nav_item.path))
                return entries

        ncx_item = None
        spine = _first(opf_root, "spine")
        toc_id = spine.get("toc") if spine is not None else None
        if toc_id and toc_id in manifest:
            ncx_item = manifest[toc_id]
        if ncx_item is None:
            for item in manifest.values():
                if item.media_type == "application/x-dtbncx+xml":
                    ncx_item = item
                    break
        if ncx_item is not None:
            entries = self._parse_ncx(ncx_item.path)
            if entries:
                self._resolve_entries(entries, posixpath.dirname(ncx_item.path))
                return entries
        return []

    def _parse_nav_document(self, path: str) -> list[TocEntry]:
        try:
            root = self._parse_xml(path, "导航文档")
        except EpubError:
            return []
        navs = _descendants(root, "nav")
        target = None
        for nav in navs:
            kind = ""
            for key, value in nav.attrib.items():
                if _local(key) == "type":
                    kind = (value or "").lower()
                    break
            if "toc" in kind.split():
                target = nav
                break
        if target is None and navs:
            target = navs[0]
        if target is None:
            return []
        entries: list[TocEntry] = []
        self._walk_nav(_first(target, "ol"), 1, entries)
        return entries

    def _walk_nav(self, ol: ET.Element | None, level: int, out: list[TocEntry]) -> None:
        if ol is None or level > 8:
            return
        for li in _children(ol, "li"):
            anchor = _first(li, "a")
            href = anchor.get("href") if anchor is not None else None
            title = _text_of(anchor)
            if not title:
                title = _text_of(_first(li, "span"))
            if title or href:
                out.append(TocEntry(title=title or "未命名", level=level, href=href or ""))
            self._walk_nav(_first(li, "ol"), level + 1, out)

    def _parse_ncx(self, path: str) -> list[TocEntry]:
        try:
            root = self._parse_xml(path, "NCX 目录文件")
        except EpubError:
            return []
        nav_map = _first(root, "navMap")
        entries: list[TocEntry] = []
        self._walk_ncx(nav_map, 1, entries)
        return entries

    def _walk_ncx(self, parent: ET.Element | None, level: int, out: list[TocEntry]) -> None:
        if parent is None or level > 8:
            return
        for point in _children(parent, "navPoint"):
            label = _first(point, "navLabel")
            title = _text_of(_first(label, "text"))
            content = _first(point, "content")
            href = content.get("src") if content is not None else ""
            if title or href:
                out.append(TocEntry(title=title or "未命名", level=level, href=href or ""))
            self._walk_ncx(point, level + 1, out)

    def _resolve_entries(self, entries: Iterable[TocEntry], base_dir: str) -> None:
        for entry in entries:
            href = entry.href.strip()
            if not href:
                continue
            path, _, fragment = href.partition("#")
            entry.anchor = unquote(fragment.strip()) or None
            if not path:
                continue
            resolved = self._resolve(base_dir, path)
            entry.chapter = self._path_index().get(resolved.lower())

    def _path_index(self) -> dict[str, int]:
        if not self._by_path:
            self._index_paths()
        return self._by_path

    def _index_paths(self) -> None:
        self._by_path = {}
        for chapter in self.chapters:
            self._by_path.setdefault(_norm_path(chapter.path).lower(), chapter.index)

    def _assign_titles(self) -> None:
        assigned: set[int] = set()
        for entry in self.toc:
            if entry.chapter is None or entry.chapter in assigned:
                continue
            if entry.title and entry.title != "未命名":
                self.chapters[entry.chapter].title = entry.title
            assigned.add(entry.chapter)
        for chapter in self.chapters:
            if not chapter.title.strip():
                chapter.title = f"第 {chapter.index + 1} 节"

    def _load_ncx_titles_fallback(self) -> None:
        """目录缺失时，用章节首个标题作为目录项。"""

        if self.toc:
            return
        for chapter in self.chapters:
            self.toc.append(
                TocEntry(title=chapter.title, level=1, chapter=chapter.index, anchor=None)
            )

    # -- 查询 ---------------------------------------------------------------

    def chapter_count(self) -> int:
        return len(self.chapters)

    def chapter_for_path(self, path: str | Path) -> int | None:
        try:
            relative = Path(path).resolve().relative_to(self.content_dir.resolve())  # type: ignore[union-attr]
        except (ValueError, AttributeError, OSError):
            return None
        key = _norm_path(relative.as_posix()).lower()
        return self._path_index().get(key)

    def describe(self) -> str:
        parts = [self.title]
        if self.author:
            parts.append(self.author)
        return " · ".join(parts)

    # -- 内部 ---------------------------------------------------------------

    def _read(self, name: str) -> bytes:
        if self._zip is None:
            raise EpubError("文件已关闭。")
        key = name.replace("\\", "/").lstrip("/").lower()
        actual = self._names.get(key)
        if actual is None:
            raise EpubError(f"缺少文件：{name}")
        return self._zip.read(actual)

    def _parse_xml(self, name: str, what: str) -> ET.Element:
        raw = self._read(name)
        try:
            return ET.fromstring(raw)
        except ET.ParseError as exc:
            raise EpubError(f"{what} 解析失败：{exc}") from exc

    @staticmethod
    def _resolve(base: str, href: str) -> str:
        href = unquote(href.split("#", 1)[0]).replace("\\", "/").strip()
        if href.startswith("/"):
            href = href[1:]
        joined = posixpath.join(base, href) if base else href
        return posixpath.normpath(joined).lstrip("/")
