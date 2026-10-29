"""生成 VideoDownload 的程序图标（多尺寸 .ico，圆角 + 立体感）。

用法：
    .venv\\Scripts\\python.exe tools\\make_icon.py

设计思路（全部在超采样大画布上绘制，最后逐级 LANCZOS 缩小）：
    1. 外投影      —— 黑色圆角矩形，向下偏移 + 高斯模糊
    2. 圆角底      —— 垂直渐变蓝 + 中心偏上的径向高光（球面感）
    3. 内描边      —— 由 mask 腐蚀得到 1px 内环，上半亮下半暗，模拟倒角
    4. 顶部高光    —— 椭圆白色柔光，让上半部分“鼓”起来
    5. 箭头        —— 自带投影，白色带轻微竖向渐变
    6. 底部托盘线  —— 同样带投影
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "videodownload.ico"
PREVIEW = ROOT / "assets" / "videodownload-preview.png"

SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

BASE = 1024          # 主绘制画布
SS = 4               # 相对于 256 的超采样倍数（1024 / 256）

# 配色
BG_TOP = (96, 165, 250)     # #60A5FA 亮蓝
BG_MID = (37, 99, 235)      # #2563EB 主蓝
BG_BOTTOM = (23, 55, 158)   # #17379E 深蓝
ARROW_TOP = (255, 255, 255)
ARROW_BOTTOM = (219, 232, 255)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _vertical_gradient(size: int) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        if t < 0.5:
            color = _lerp(BG_TOP, BG_MID, t / 0.5)
        else:
            color = _lerp(BG_MID, BG_BOTTOM, (t - 0.5) / 0.5)
        grad.putpixel((0, y), color)
    return grad.resize((size, size), Image.BICUBIC).convert("RGBA")


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255
    )
    return mask


def draw_icon(size: int = BASE) -> Image.Image:
    s = size
    radius = int(s * 0.235)          # 明显圆角，接近 iOS / Win11 图标比例
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # ---------- 1. 外投影 ----------
    shadow_pad = int(s * 0.055)
    shadow_mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(shadow_mask).rounded_rectangle(
        [shadow_pad, shadow_pad * 1.2, s - 1 - shadow_pad, s - 1 - shadow_pad * 0.6],
        radius=radius,
        fill=150,
    )
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(s * 0.030))
    shadow = Image.new("RGBA", (s, s), (8, 20, 60, 255))
    canvas.paste(shadow, (0, 0), shadow_mask)

    # ---------- 2. 圆角底 + 径向高光 ----------
    body = _vertical_gradient(s)

    # 径向高光：radial_gradient 中心 0、边缘 255，反相后中心最亮
    radial = Image.radial_gradient("L").resize((s, s), Image.BICUBIC)
    glow = ImageChops.invert(radial).point(lambda v: int(v * 0.30))
    # 把高光中心上移，模拟顶部受光
    offset = int(s * 0.16)
    shifted = Image.new("L", (s, s), 0)
    shifted.paste(glow, (0, -offset))
    body = Image.composite(Image.new("RGBA", (s, s), (255, 255, 255, 255)), body, shifted.point(lambda v: v // 3))

    mask = _rounded_mask(s, radius)
    canvas.paste(body, (0, 0), mask)

    # ---------- 3. 内描边（倒角） ----------
    eroded = mask.filter(ImageFilter.MinFilter(5))      # 内缩，得到内环
    inner_ring = ImageChops.subtract(mask, eroded)
    # 上半亮、下半暗：用垂直渐变当 alpha
    bevel_alpha = Image.new("L", (1, s))
    for y in range(s):
        t = y / max(1, s - 1)
        bevel_alpha.putpixel((0, y), int(150 * (1 - t) ** 1.5))
    bevel_alpha = bevel_alpha.resize((s, s), Image.BICUBIC)
    ring = ImageChops.multiply(inner_ring, bevel_alpha)
    canvas.paste(Image.new("RGBA", (s, s), (255, 255, 255, 255)), (0, 0), ring)

    # 底部暗边（让下沿更“厚”）
    dark_alpha = Image.new("L", (1, s))
    for y in range(s):
        t = y / max(1, s - 1)
        dark_alpha.putpixel((0, y), int(90 * t ** 2))
    dark_alpha = dark_alpha.resize((s, s), Image.BICUBIC)
    dark_ring = ImageChops.multiply(inner_ring, dark_alpha)
    canvas.paste(Image.new("RGBA", (s, s), (10, 22, 60, 255)), (0, 0), dark_ring)

    # ---------- 4. 顶部椭圆柔光 ----------
    hl = Image.new("L", (s, s), 0)
    ImageDraw.Draw(hl).ellipse(
        [-int(s * 0.18), -int(s * 0.52), s + int(s * 0.18), int(s * 0.44)],
        fill=70,
    )
    hl = hl.filter(ImageFilter.GaussianBlur(s * 0.055))
    hl = ImageChops.multiply(hl, mask)
    canvas.paste(Image.new("RGBA", (s, s), (255, 255, 255, 255)), (0, 0), hl)

    # ---------- 5. 箭头（带投影 + 竖向渐变） ----------
    glyph = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph)
    cx = s / 2

    stem_w = s * 0.135
    stem_top = s * 0.255
    stem_bottom = s * 0.555
    head_w = s * 0.455
    head_top = s * 0.485
    head_bottom = s * 0.745

    # 竖向渐变填充用 mask 实现
    arrow_mask = Image.new("L", (s, s), 0)
    am = ImageDraw.Draw(arrow_mask)
    am.rounded_rectangle(
        [cx - stem_w / 2, stem_top, cx + stem_w / 2, stem_bottom],
        radius=stem_w * 0.34,
        fill=255,
    )
    am.polygon(
        [
            (cx - head_w / 2, head_top),
            (cx + head_w / 2, head_top),
            (cx, head_bottom),
        ],
        fill=255,
    )
    # 托盘线
    tray_w = s * 0.545
    tray_h = s * 0.088
    tray_y = s * 0.815
    am.rounded_rectangle(
        [cx - tray_w / 2, tray_y, cx + tray_w / 2, tray_y + tray_h],
        radius=tray_h / 2,
        fill=255,
    )

    # 投影：整体下移 + 模糊
    drop = arrow_mask.filter(ImageFilter.GaussianBlur(s * 0.016))
    drop = drop.point(lambda v: int(v * 0.45))
    shadow_layer = Image.new("RGBA", (s, s), (12, 28, 72, 255))
    canvas.paste(shadow_layer, (0, int(s * 0.014)), drop)

    # 箭头本体：白 → 淡蓝 的竖向渐变
    fill = Image.new("RGB", (1, s))
    y0, y1 = int(stem_top), int(tray_y + tray_h)
    for y in range(s):
        if y <= y0:
            t = 0.0
        elif y >= y1:
            t = 1.0
        else:
            t = (y - y0) / max(1, y1 - y0)
        fill.putpixel((0, y), _lerp(ARROW_TOP, ARROW_BOTTOM, t))
    fill = fill.resize((s, s), Image.BICUBIC).convert("RGBA")
    canvas.paste(fill, (0, 0), arrow_mask)

    # 箭头内侧顶部高光，让字形本身也有厚度
    inner_hl = Image.new("L", (s, s), 0)
    ImageDraw.Draw(inner_hl).rounded_rectangle(
        [cx - stem_w / 2 + 2 * SS, stem_top + 2 * SS,
         cx + stem_w / 2 - 2 * SS, stem_top + s * 0.045],
        radius=stem_w * 0.3,
        fill=255,
    )
    inner_hl = ImageChops.multiply(inner_hl, arrow_mask).filter(
        ImageFilter.GaussianBlur(s * 0.006)
    )
    canvas.paste(Image.new("RGBA", (s, s), (255, 255, 255, 255)), (0, 0), inner_hl)

    return canvas


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    master = draw_icon(BASE).resize((256, 256), Image.LANCZOS)

    frames = [master.resize((n, n), Image.LANCZOS) for n in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])
    master.resize((512, 512), Image.LANCZOS).save(PREVIEW, format="PNG")

    print(f"已生成 {OUT}")
    print(f"尺寸：{', '.join(str(n) for n in SIZES)}")
    print(f"预览：{PREVIEW}")


if __name__ == "__main__":
    build()
