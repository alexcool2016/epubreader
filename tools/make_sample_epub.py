"""生成用于测试的示例 EPUB（含 EPUB3 nav 与 EPUB2 NCX 两套目录）。

用法： python tools/make_sample_epub.py [输出路径]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

CHAPTERS = [
    (
        "第一章 起风了",
        "wind",
        [
            ("h1", "第一章 起风了"),
            ("p", "海边的风从清晨开始就没有停过。林间的树影随风摇摆，"
                  "像是在低声诉说着什么古老的秘密。"),
            ("h2", "第一节 潮声"),
            ("p", "潮水一遍遍地拍打着礁石，声音沉闷而有节奏。每当夜色降临，"
                  "远处的灯塔便会亮起，把海面切割成一条条光带。"),
            ("p", "“你听见了吗？”老人问道，“那是海在呼吸。”"),
            ("h2", "第二节 灯塔"),
            ("p", "灯塔的守夜人已经在这里工作了三十年。他记得每一艘经过的船，"
                  "也记得每一次风暴来临之前的空气味道。"),
        ],
    ),
    (
        "第二章 旧信",
        "letters",
        [
            ("h1", "第二章 旧信"),
            ("p", "阁楼的木箱里塞满了泛黄的信件，纸张边缘已经发脆。"
                  "字迹是那种老一辈人特有的、认真到近乎固执的端正。"),
            ("blockquote", "“见字如面。今年的雨来得格外早，院子里的桂花还没开。”"),
            ("p", "信里写的大多是琐事：天气、收成、邻里的婚丧嫁娶。"
                  "可正是这些琐事，让一个已经消失的时代重新有了温度。"),
            ("h2", "第一节 一封信的重量"),
            ("p", "有人说，一封信的重量取决于它寄托了多少等待。"
                  "在这个即时通讯的时代，等待本身已经成为一种奢侈。"),
        ],
    ),
    (
        "第三章 归途",
        "return",
        [
            ("h1", "第三章 归途"),
            ("p", "火车在夜里穿过平原，窗外的灯火一闪而过，像被抛在身后的星星。"),
            ("ul", None),
            ("li", "第一站：故乡的车站，月台上只有一盏灯。"),
            ("li", "第二站：老屋，门前的桂花树已经长得比屋檐还高。"),
            ("li", "第三站：海边，风依旧，灯塔依旧。"),
            ("p", "他终于明白，所谓归途，从来不是回到某个地方，"
                  "而是回到某种心境。风还在吹，潮声还在响，"
                  "而他已经不再害怕这些声音了。"),
        ],
    ),
]


def _chapter_html(title: str, body: list[tuple[str, str | None]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
        '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml">',
        "<head><title>" + title + "</title></head>",
        "<body>",
    ]
    for tag, text in body:
        if tag == "ul":
            parts.append("<ul>")
        elif tag == "li":
            parts.append(f"<li>{text}</li>")
        else:
            parts.append(f"<{tag}>{text}</{tag}>")
    parts.append("</ul>")
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)


def build(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    chapter_files = [(f"text/ch{i + 1}.xhtml", data) for i, (_, slug, data) in enumerate(CHAPTERS)]

    nav_items = "\n".join(
        f'      <li><a href="{name}">{title}</a></li>'
        for (name, _), (title, _, _) in zip(chapter_files, CHAPTERS)
    )
    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>目录</h1>
    <ol>
{nav_items}
    </ol>
  </nav>
</body>
</html>
"""

    nav_points = []
    for order, ((name, _), (title, _, _)) in enumerate(zip(chapter_files, CHAPTERS), start=1):
        nav_points.append(
            f"""    <navPoint id="np{order}" playOrder="{order}">
      <navLabel><text>{title}</text></navLabel>
      <content src="{name}"/>
    </navPoint>"""
        )
    ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:sample-epub-reader"/>
    <meta name="dtb:depth" content="1"/>
  </head>
  <docTitle><text>海边的灯塔</text></docTitle>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>
"""

    manifest_items = "\n".join(
        f'    <item id="ch{i + 1}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, (name, _) in enumerate(chapter_files)
    )
    spine_items = "\n".join(
        f'    <itemref idref="ch{i + 1}"/>' for i in range(len(chapter_files))
    )
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:sample-epub-reader</dc:identifier>
    <dc:title>海边的灯塔</dc:title>
    <dc:creator>示例作者</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
{manifest_items}
  </manifest>
  <spine toc="ncx">
{spine_items}
  </spine>
</package>
"""

    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/nav.xhtml", nav)
        archive.writestr("OEBPS/toc.ncx", ncx)
        for (name, _), (title, _, _) in zip(chapter_files, CHAPTERS):
            archive.writestr(f"OEBPS/{name}", _chapter_html(title, _))
    return target


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples/sample.epub")
    path = build(out)
    print(f"已生成示例 EPUB：{path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
