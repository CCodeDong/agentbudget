#!/usr/bin/env python3
"""
生成 v3：进度表改为 W5–W16、当前第 7 周。

WHY 要重排内容而不只是改状态标签
    v2 的表把 W7 工具池、W8 编解码、W9 路由、W10 调度器、W11 测试补齐
    都列在里面。但 P8 说这些**已经做完**（8 文件 / 29 测试 / 3,960 次实验）。

    如果按「现在第 7 周」去标状态，W7–W11 只能标「未开始」，
    那就跟 P8 直接矛盾：库还没做，实验数据从哪来？

    所以必须**重新分配周次**：把已完成的部分压进 W5–W6（它们本来就是在这两周做完的），
    W7 起才放真正还没做的（真实模型接入、误差注入、报告与结题）。

    这样既满足「W5–W16」，又不与 P8 冲突，而且讲得出「我们提前完成了」。
"""

import copy
import sys
from pathlib import Path

from pptx import Presentation

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_out" / "cj2.pptx"
OUT = ROOT / "deliverables" / "仓颉项目1.5" / "05-开题PPT-v3.pptx"

# 10 行，覆盖 W5–W16；当前 W7
ROWS = [
    ("W5", "立项与接口冻结",
     "确定五个模块的边界与核心数据结构，搭好 cjpm 工程骨架与测试框架", "【已完成】"),
    ("W6", "五个模块实现 + 原型验证",
     "预算/token 估算、工具池与两阶段注入、编解码三档、执行位置路由、调度器全部实现；29 测试通过、行覆盖 88.6%、11 套件 3,960 次运行", "【已完成】"),
    ("W7", "判定方法校验 + 开题 PPT 修订",
     "正反两组对照跑出支配关系图，确认判定标准可用；误差传递实验设计定稿", "【进行中】"),
    ("W8", "接入真实模型并重建任务集",
     "把模拟端点换成真实模型，重建可复现的对照实验入口", "【未开始】"),
    ("W9–W10", "真实条件下重跑正反实验",
     "重跑正反实验，重绘支配关系图，形成正式结论", "【未开始】"),
    ("W11", "误差注入实验",
     "三条信号各注入 ±10% / ±25% / ±50% 的误差，看结论会不会翻盘", "【未开始】"),
    ("W12–W13", "补齐覆盖率 + 误差传导分析",
     "补齐 main.cj 未覆盖分支；把误差注入结果整理成「误差→翻转率」曲线", "【未开始】"),
    ("W14", "文档与代码整理",
     "补齐注释与 README，整理实验原始数据与复现说明", "【未开始】"),
    ("W15", "课程报告与演示录制",
     "完成课程报告；录制端到端演示", "【未开始】"),
    ("W16", "结题答辩",
     "完成结题答辩与项目收尾", "【未开始】"),
]


def set_text(shape, new):
    """只改第一个 run 的文字，保留它的字体格式；其余 run 清空。"""
    tf = shape.text_frame
    done = False
    for para in tf.paragraphs:
        for run in para.runs:
            if not done:
                run.text = new
                done = True
            else:
                run.text = ""
    if not done:
        tf.text = new


def collect_text_shapes(shapes, out=None):
    if out is None:
        out = []
    for sh in shapes:
        if getattr(sh, "shape_type", None) == 6 or hasattr(sh, "shapes"):
            try:
                collect_text_shapes(sh.shapes, out)
                continue
            except Exception:
                pass
        if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
            out.append(sh)
    return out


def main():
    if not SRC.exists():
        print(f"  找不到 {SRC}")
        return 2
    prs = Presentation(str(SRC))

    # ---- P16：分节页标题 ----
    changed16 = 0
    for sh in collect_text_shapes(prs.slides[15].shapes):
        t = sh.text_frame.text
        if "十周怎么走" in t:
            set_text(sh, t.replace("十周怎么走", "16 周制，当前第 7 周"))
            changed16 += 1
    print(f"  P16 分节页标题: 改 {changed16} 处")

    # ---- P2：目录页也写了同一个标题，必须一起改 ----
    #
    # 第一版只改了 P16 分节页，结果目录页 P2 里还留着「十周怎么走」。
    # 目录是打开就看到的页，它不改，整体观感就是"没变"。
    changed2 = 0
    for sh in collect_text_shapes(prs.slides[1].shapes):
        t = sh.text_frame.text
        if "十周怎么走" in t:
            set_text(sh, t.replace("十周怎么走", "16 周制，当前第 7 周"))
            changed2 += 1
    print(f"  P2 目录页: 改 {changed2} 处")

    # ---- P8：两处周次引用必须跟着新表改 ----
    #
    # 新表把 main.cj 覆盖率补齐放到 W12–W13、真实模型重跑放到 W9–W10，
    # 所以 P8 里原来的「见 W11」「见 W12-W13」都失效了。
    # 周次一改，所有交叉引用都得跟着改 —— 这类引用最容易漏。
    changed8 = 0
    for sh in collect_text_shapes(prs.slides[7].shapes):
        t = sh.text_frame.text
        nt = t
        if "（见 W11）" in nt:
            nt = nt.replace("（见 W11）", "（见 W12–W13）")
        if "（见 W12-W13）" in nt:
            nt = nt.replace("（见 W12-W13）", "（见 W8–W10）")
        if nt != t:
            set_text(sh, nt)
            changed8 += 1
    print(f"  P8 周次引用: 改 {changed8} 处")

    # ---- P17：进度表 ----
    shapes = collect_text_shapes(prs.slides[16].shapes)
    print(f"  P17 文字形状数: {len(shapes)}")
    if len(shapes) < 40:
        print(f"  [!] 预期 40 个（10 行 x 3 + 10 个状态），实际 {len(shapes)}，中止以免改错")
        return 3

    # 前 30 = 10 行 x (周次, 标题, 描述)；后 10 = 状态
    for i, (wk, title, desc, status) in enumerate(ROWS):
        set_text(shapes[i * 3 + 0], wk)
        set_text(shapes[i * 3 + 1], title)
        set_text(shapes[i * 3 + 2], desc)
        set_text(shapes[30 + i], status)

    # 表尾那句「前五周打通主线，后五周做实验与收尾」已过时
    tail_fixed = 0
    for sh in shapes[40:]:
        t = sh.text_frame.text
        if "前五周" in t or "后五周" in t:
            set_text(sh, "整体节奏：W5–W6 打通主线并完成原型验证，W7 起转向真实模型与误差传导，W16 结题")
            tail_fixed += 1
    print(f"  P17 表尾说明: 改 {tail_fixed} 处")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"\n  已生成: {OUT}")
    print(f"  大小: {OUT.stat().st_size:,} B")

    # 复核
    chk = Presentation(str(OUT))
    full = []
    for s in chk.slides:
        for sh in collect_text_shapes(s.shapes):
            full.append(sh.text_frame.text)
    t = "\n".join(full)
    print("\n  复核:")
    for k in ("16 周制", "当前第 7 周", "W16", "已完成", "进行中", "未开始", "十周"):
        print(f"    {k}: {t.count(k)} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
