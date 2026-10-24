"""不依赖图形界面的冒烟测试：解析示例 EPUB 并做全文搜索。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from epubreader.book import EpubBook  # noqa: E402
from epubreader.search import SearchOptions, search_book  # noqa: E402
from tools.make_sample_epub import build  # noqa: E402


def main() -> int:
    sample = build(Path("samples/sample.epub"))
    book = EpubBook.open(sample, progress=lambda d, t, m: None)
    print(f"标题: {book.title}")
    print(f"作者: {book.author}")
    print(f"章节数: {book.chapter_count()}")
    for chapter in book.chapters:
        print(f"  [{chapter.index}] {chapter.title}  正文 {len(chapter.text)} 字，块 {len(chapter.blocks)} 个")
        assert chapter.file.exists(), f"预处理文件缺失: {chapter.file}"
        assert "<script" not in chapter.file.read_text(encoding="utf-8").lower()

    print(f"目录项: {len(book.toc)}")
    for entry in book.toc:
        print(f"  {'  ' * (entry.level - 1)}{entry.title} -> 章节 {entry.chapter} 锚点 {entry.anchor}")

    hits = search_book(book, SearchOptions(query="灯塔"))
    print(f"\n搜索“灯塔”: {len(hits)} 处")
    for hit in hits[:5]:
        print(f"  章节 {hit.chapter}: …{hit.prefix}{hit.matched}{hit.suffix}…")

    hits_case = search_book(book, SearchOptions(query="灯塔", match_case=True))
    hits_word = search_book(book, SearchOptions(query="风", whole_word=True))
    print(f"区分大小写: {len(hits_case)} 处；整词“风”: {len(hits_word)} 处")

    block = next((b for b in book.chapters[0].blocks if b[0] > 0), None)
    print(f"\n首个可定位块: {block}")
    path_index = book.chapter_for_path(book.content_dir / "OEBPS/text/ch2.xhtml")
    print(f"路径反查章节: {path_index}")
    assert path_index == 1
    assert hits, "示例书籍应包含“灯塔”"
    assert len(book.chapters) == 3

    book.close()
    print("\n冒烟测试通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
