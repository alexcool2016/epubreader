"""生成程序图标 assets/app.ico（深色圆角底 + 灯塔与光束）。

用法： python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BASE = 1024
SIZES = [16, 24, 32, 48, 64, 128, 256]

TOP_BG = (23, 32, 43)
BOTTOM_BG = (36, 56, 74)
CREAM = (245, 241, 230)
AMBER = (232, 163, 61)
AMBER_DARK = (201, 119, 42)
SEA = (63, 111, 138)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _tower_width(y: float) -> tuple[float, float]:
    """返回塔身在给定 y 处的左右边界（线性收缩）。"""

    t = (y - 430) / (800 - 430)
    t = min(1.0, max(0.0, t))
    left = 484 - (484 - 455) * t
    right = 540 + (569 - 540) * t
    return left, right


def _band(draw: ImageDraw.ImageDraw, y1: float, y2: float, color) -> None:
    l1, r1 = _tower_width(y1)
    l2, r2 = _tower_width(y2)
    draw.polygon([(l1, y1), (r1, y1), (r2, y2), (l2, y2)], fill=color)


def render() -> Image.Image:
    # 背景：纵向渐变 + 圆角遮罩
    grad = Image.new("RGB", (BASE, BASE))
    gd = ImageDraw.Draw(grad)
    for y in range(BASE):
        gd.line([(0, y), (BASE, y)], fill=_lerp(TOP_BG, BOTTOM_BG, y / (BASE - 1)))

    mask = Image.new("L", (BASE, BASE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, BASE - 1, BASE - 1], radius=int(BASE * 0.215), fill=255
    )

    img = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    # 光束（先画，位于塔身后方）
    beams = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    bd = ImageDraw.Draw(beams)
    bd.polygon([(512, 405), (120, 300), (120, 470)], fill=(255, 214, 130, 70))
    bd.polygon([(512, 405), (904, 300), (904, 470)], fill=(255, 214, 130, 70))
    img = Image.alpha_composite(img, beams)

    draw = ImageDraw.Draw(img)

    # 塔身
    l, r = _tower_width(430)
    lb, rb = _tower_width(800)
    draw.polygon([(l, 430), (r, 430), (rb, 800), (lb, 800)], fill=CREAM)

    # 塔身条纹
    for y1, y2 in ((470, 522), (568, 620), (666, 718)):
        _band(draw, y1, y2, AMBER)

    # 灯室
    draw.rounded_rectangle([470, 388, 554, 436], radius=10, fill=AMBER_DARK)
    draw.rounded_rectangle([482, 398, 542, 428], radius=6, fill=(255, 236, 186))

    # 塔顶
    draw.polygon([(458, 390), (566, 390), (512, 344)], fill=AMBER_DARK)

    # 海浪
    draw.rounded_rectangle([196, 796, 828, 828], radius=16, fill=SEA)
    draw.rounded_rectangle([252, 848, 772, 876], radius=14, fill=(48, 88, 112))

    return img


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    img = render()

    png_path = ASSETS / "app.png"
    img.resize((256, 256), Image.LANCZOS).save(png_path)

    ico_path = ASSETS / "app.ico"
    frames = [img.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in SIZES])

    print(f"已生成：{ico_path}")
    print(f"已生成：{png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
