#!/usr/bin/env python3
"""
生成应用图标候选与分层图标。

HARMONYOS 分层图标的规矩
    background : 288×288 满幅（会铺满整个图标区域）
    foreground : 288×288 透明，图形要落在中间约 60% 的安全区内
                 （系统会按设备做圆角/圆形裁切，画到边上会被切掉）

    所以前景不能画满，否则在圆形裁切下会缺角。
    这里把图形限制在中间 168×168（58%）内，留足余量。

封面图标（AGC 用）216×216，直接把背景 + 前景合成。
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "offlinelib"
PREVIEW = ROOT / "deliverables" / "上架材料" / "图标"

C_BG_TOP = (18, 62, 158)      # 深蓝
C_BG_BOT = (10, 89, 247)      # 亮蓝（与界面 accent 同色系）
C_WHITE = (255, 255, 255)


def gradient(size, top, bot):
    img = Image.new("RGB", (size, size), top)
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (size, y)], fill=c)
    return img


def glyph_document(d, cx, cy, s, color=C_WHITE):
    """一张带折角的纸 + 三条文字线。"""
    w, h = s * 0.62, s * 0.80
    x0, y0 = cx - w / 2, cy - h / 2
    fold = s * 0.20
    # 纸身（右上角折角）
    d.polygon([
        (x0, y0), (x0 + w - fold, y0), (x0 + w, y0 + fold),
        (x0 + w, y0 + h), (x0, y0 + h)
    ], fill=color)
    # 折角缺口（用背景色挖，这里用透明处理不了，改画三角）
    d.polygon([(x0 + w - fold, y0), (x0 + w - fold, y0 + fold), (x0 + w, y0 + fold)],
              fill=(0, 0, 0, 0) if d.mode == "RGBA" else None)
    # 文字线（用背景渐变近似的深色）
    lw = w * 0.52
    for k in range(3):
        ly = y0 + h * (0.30 + k * 0.17)
        d.rounded_rectangle([x0 + w * 0.18, ly, x0 + w * 0.18 + lw * (1 - 0.18 * k), ly + h * 0.055],
                            radius=h * 0.028, fill=C_BG_BOT)


def glyph_magnifier(d, cx, cy, r, thickness, color=C_BG_TOP):
    """放大镜：圆环 + 手柄。"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=int(thickness))
    import math
    a = math.radians(45)
    x1, y1 = cx + r * math.cos(a) * 0.86, cy + r * math.sin(a) * 0.86
    x2, y2 = cx + r * math.cos(a) * 1.62, cy + r * math.sin(a) * 1.62
    d.line([(x1, y1), (x2, y2)], fill=color, width=int(thickness * 1.15))


def draw_A(d, cx, cy, s):
    """A：文档 + 放大镜（最直白）"""
    glyph_document(d, cx - s * 0.06, cy - s * 0.02, s * 0.92)
    glyph_magnifier(d, cx + s * 0.20, cy + s * 0.18, s * 0.20, s * 0.065)


def draw_B(d, cx, cy, s):
    """B：三张卡片堆叠 + 放大镜"""
    for k, off in enumerate((0.10, 0.05, 0.0)):
        w, h = s * 0.60, s * 0.42
        x0 = cx - w / 2 + off * s * 0.5
        y0 = cy - h / 2 + off * s * 0.5
        col = (255, 255, 255, 150 + k * 50) if d.mode == "RGBA" else C_WHITE
        d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=s * 0.05, fill=col)
    glyph_magnifier(d, cx + s * 0.22, cy + s * 0.20, s * 0.19, s * 0.062)


def draw_C(d, cx, cy, s):
    """C：库字 + 下划线（最有辨识度，但要字体支持）"""
    f = None
    for cand in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
                 r"C:\Windows\Fonts\simhei.ttf"):
        try:
            f = ImageFont.truetype(cand, int(s * 0.62))
            break
        except Exception:
            continue
    if f is None:
        return draw_A(d, cx, cy, s)
    tw = d.textlength("库", font=f)
    d.text((cx - tw / 2, cy - s * 0.34), "库", font=f, fill=C_WHITE)
    # 下划线：像书架
    d.rounded_rectangle([cx - s * 0.30, cy + s * 0.30, cx + s * 0.30, cy + s * 0.36],
                        radius=s * 0.03, fill=C_WHITE)


DRAWERS = {"A": draw_A, "B": draw_B, "C": draw_C}
DESC = {
    "A": "文档 + 放大镜（最直白：能搜的文档）",
    "B": "卡片堆叠 + 放大镜（强调资料库）",
    "C": "「库」字 + 书架线（最有辨识度）",
}


def make_foreground(size, key):
    """透明前景，图形限制在中间 58% 的安全区。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size * 0.58
    DRAWERS[key](d, size / 2, size / 2, s)
    return img


def apply_to_project(key):
    """
    把选定方案的图标写进工程。

    四个文件各有用处，尺寸不能混：
      app_icon.png    216x216  封面图标（AGC 上架用）
      background.png  288x288  分层图标背景层（满幅）
      foreground.png  288x288  分层图标前景层（透明，图形在 58% 安全区）
      startIcon.png   144x144  启动页图标
    前景与背景必须分开存：系统自己合成，并按设备做圆形/圆角裁切。
    合成后的图案只能用于封面和启动页。
    """
    media_e = APP / "entry" / "src" / "main" / "resources" / "base" / "media"
    media_a = APP / "AppScope" / "resources" / "base" / "media"

    bg288 = gradient(288, C_BG_TOP, C_BG_BOT).convert("RGBA")
    fg288 = make_foreground(288, key)
    cover288 = Image.alpha_composite(bg288, fg288)

    cover288.resize((216, 216), Image.LANCZOS).save(media_a / "app_icon.png")
    bg288.convert("RGB").save(media_e / "background.png")
    fg288.save(media_e / "foreground.png")
    cover288.resize((144, 144), Image.LANCZOS).save(media_e / "startIcon.png")

    print("  已写入工程：")
    for name, size in (("AppScope/app_icon.png", "216x216"),
                       ("entry/background.png", "288x288"),
                       ("entry/foreground.png", "288x288"),
                       ("entry/startIcon.png", "144x144")):
        print(f"    {name:28} {size}")

    print("")
    print("  复核：")
    checks = ((media_a / "app_icon.png", (216, 216)),
              (media_e / "background.png", (288, 288)),
              (media_e / "foreground.png", (288, 288)),
              (media_e / "startIcon.png", (144, 144)))
    for path, want in checks:
        im = Image.open(path)
        ok = im.size == want
        print(f"    {path.name:18} {im.size[0]}x{im.size[1]}  {'[OK]' if ok else '[尺寸不对]'}")
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] == "apply":
        key = args[1].upper() if len(args) > 1 else "A"
        if key not in DRAWERS:
            print(f"  未知方案 {key}，可选 A / B / C")
            return 2
        print("=" * 74)
        print(f"应用图标方案 {key} 写入工程")
        print("=" * 74)
        rc = apply_to_project(key)
        print("")
        print("  下一步：重新构建 HAP，确认桌面图标已变。")
        return rc

    PREVIEW.mkdir(parents=True, exist_ok=True)(parents=True, exist_ok=True)
    made = []

    for key in ("A", "B", "C"):
        bg = gradient(288, C_BG_TOP, C_BG_BOT).convert("RGBA")
        fg = make_foreground(288, key)
        composed = Image.alpha_composite(bg, fg)

        # 候选预览（216×216，AGC 封面图标尺寸）
        cover = composed.resize((216, 216), Image.LANCZOS)
        p = PREVIEW / f"候选{key}-216.png"
        cover.save(p)
        made.append((key, p))

        # 圆形裁切预览，检查安全区
        circ = Image.new("RGBA", (216, 216), (245, 247, 250, 255))
        mask = Image.new("L", (216, 216), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, 215, 215], fill=255)
        circ.paste(cover, (0, 0), mask)
        q = PREVIEW / f"候选{key}-圆形裁切.png"
        circ.save(q)

    # 拼一张对比图
    sheet = Image.new("RGB", (216 * 3 + 40, 216 + 70), (245, 247, 250))
    sd = ImageDraw.Draw(sheet)
    try:
        fnt = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 18)
    except Exception:
        fnt = ImageFont.load_default()
    for i, (key, p) in enumerate(made):
        sheet.paste(Image.open(p).convert("RGB"), (10 + i * (216 + 10), 10))
        sd.text((10 + i * (216 + 10), 236), f"{key}: {DESC[key][:12]}", font=fnt, fill=(40, 40, 40))
    sheet_p = PREVIEW / "候选对比.png"
    sheet.save(sheet_p)

    print("=" * 74)
    print("图标候选")
    print("=" * 74)
    for key, p in made:
        print(f"  {key}  {DESC[key]}")
        print(f"       {p.name}")
    print(f"\n  对比图：{sheet_p.name}")
    print(f"  输出目录：{PREVIEW}")
    print("\n  [!] 选定后我才会写进工程的 layered_image / app_icon。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
