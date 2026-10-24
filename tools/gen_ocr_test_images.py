#!/usr/bin/env python3
"""
生成 OCR 质量测试图集。

WHY SYNTHETIC IMAGES WITH KNOWN ANSWERS
    测 OCR 质量最怕"看着还行" —— 那不是测量，是印象。

    这些图是我们自己生成的，所以**正确答案是已知的**。
    这样就能算出字符级召回率/精确率，把"模糊一点会不会变差"
    变成一个可以写进报告的百分比。

    局限也要说清楚：合成图不等于真实拍摄 ——
    没有反光、没有透视畸变、没有纸张纹理。
    它测的是"同一段文字在不同退化条件下的识别率"，
    不是"在真实照片上的识别率"。

WHTY THE SAME TEXT IN EVERY IMAGE
    如果每张图内容不同，就无法区分"变差是因为质量"还是"因为内容难"。
    所以七张图共用同一段基准文字，只改变退化方式。

OUTPUT
    直接写进应用的 rawfile 目录，随 HAP 打包。
"""

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "resources" / "rawfile"

# 基准文字：与 manifest 里的 GROUND_TRUTH 必须完全一致。
# 之所以单独放在这里而不是从别处读，是为了让这个脚本可以独立运行。
LINES = [
    "上下文窗口只有四千到八千",
    "多智能体消耗约为十五倍",
    "因此取舍是强制的",
    "BM25 排序 k1=1.5",
]
GROUND_TRUTH = "".join(LINES)

SIZE = (900, 420)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return None


def base_canvas(bg=WHITE):
    img = Image.new("RGB", SIZE, bg)
    return img


def draw_lines(img, fnt, fill=BLACK, x=70, y=60, gap=75):
    d = ImageDraw.Draw(img)
    for i, line in enumerate(LINES):
        d.text((x, y + i * gap), line, font=fnt, fill=fill)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # 字体
    hei = font(r"C:\Windows\Fonts\simhei.ttf", 40) or ImageFont.load_default()
    kai = font(r"C:\Windows\Fonts\STKAITI.TTF", 40) or hei
    xing = font(r"C:\Windows\Fonts\STXINGKA.TTF", 42) or hei
    small = font(r"C:\Windows\Fonts\simhei.ttf", 18) or hei

    made = []

    # 1 清晰
    img = draw_lines(base_canvas(), hei)
    p = OUT / "q1_clean.png"
    img.save(p)
    made.append(("清晰（基准）", p, "无退化"))

    # 2 模糊：模拟失焦/手抖
    img = draw_lines(base_canvas(), hei)
    img = img.filter(ImageFilter.GaussianBlur(radius=2.2))
    p = OUT / "q2_blur.png"
    img.save(p)
    made.append(("高斯模糊", p, "radius=2.2"))

    # 3 低对比：模拟暗光拍摄
    img = draw_lines(base_canvas((235, 235, 228)), hei, fill=(175, 175, 168))
    p = OUT / "q3_lowcontrast.png"
    img.save(p)
    made.append(("低对比", p, "浅灰字/浅灰底"))

    # 4 轻微旋转：模拟手持倾斜
    img = draw_lines(base_canvas(), hei).rotate(6.5, expand=False, fillcolor=WHITE)
    p = OUT / "q4_rotated.png"
    img.save(p)
    made.append(("旋转 6.5°", p, "模拟手持倾斜"))

    # 5 小字：模拟远距离拍摄
    img = draw_lines(base_canvas(), small, y=80, gap=45)
    p = OUT / "q5_small.png"
    img.save(p)
    made.append(("小字号", p, "18px（其余 40px）"))

    # 6 楷体：最接近手写印刷体的一档
    img = draw_lines(base_canvas(), kai, y=55, gap=80)
    p = OUT / "q6_kaiti.png"
    img.save(p)
    made.append(("楷体", p, "模拟手写风格"))

    # 7 行楷：更接近真手写
    img = draw_lines(base_canvas(), xing, y=55, gap=82)
    p = OUT / "q7_xingkai.png"
    img.save(p)
    made.append(("行楷", p, "更接近手写"))

    # --- 第二档：刻意加大退化，目的是找到断点 ---
    #
    # 第一档 12 张里除行楷外全部 100%，说明**强度不够**。
    # 只报"全部通过"是没有信息量的：它不能说明"真实照片也没问题"，
    # 只说明"这几张合成图对 Vision Kit 来说太简单"。
    # 所以再加一档明显更狠的，看它从哪里开始掉。

    # 8 强模糊：接近明显失焦
    img = draw_lines(base_canvas(), hei)
    img = img.filter(ImageFilter.GaussianBlur(radius=5.0))
    p = OUT / "q8_blur_strong.png"
    img.save(p)
    made.append(("强模糊", p, "radius=5.0"))

    # 9 极低对比：字与底几乎同色
    img = draw_lines(base_canvas((242, 242, 238)), hei, fill=(206, 206, 200))
    p = OUT / "q9_contrast_extreme.png"
    img.save(p)
    made.append(("极低对比", p, "206/242"))

    # 10 大角度旋转
    img = draw_lines(base_canvas(), hei).rotate(15, expand=False, fillcolor=WHITE)
    p = OUT / "q10_rotated15.png"
    img.save(p)
    made.append(("旋转 15°", p, "明显倾斜"))

    # 11 椒盐噪声：模拟高 ISO / 低光噪点
    rnd = random.Random(42)
    img = draw_lines(base_canvas(), hei)
    px = img.load()
    w, h = img.size
    for yy in range(h):
        for xx in range(w):
            r0, g0, b0 = px[xx, yy]
            n = rnd.randint(-55, 55)
            px[xx, yy] = (max(0, min(255, r0 + n)),
                          max(0, min(255, g0 + n)),
                          max(0, min(255, b0 + n)))
    p = OUT / "q11_noisy.png"
    img.save(p)
    made.append(("噪声", p, "±55 随机噪点"))

    # 12 组合退化：小字 + 模糊
    img = draw_lines(base_canvas(), small, y=80, gap=45)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.6))
    p = OUT / "q12_small_blur.png"
    img.save(p)
    made.append(("小字+模糊", p, "18px + radius1.6"))

    print("=" * 74)
    print("OCR 质量测试图集")
    print("=" * 74)
    print(f"  基准文字（{len(GROUND_TRUTH)} 字）：")
    for line in LINES:
        print(f"    {line}")
    print()
    print(f"  {'文件':<20} {'退化方式':<20} {'体积':>9}")
    print("  " + "-" * 54)
    for desc, p, note in made:
        print(f"  {p.name:<20} {note:<20} {p.stat().st_size:>8,} B")
    print()
    print(f"  输出目录：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
