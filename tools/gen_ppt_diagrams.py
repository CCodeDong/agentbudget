#!/usr/bin/env python3
"""
补两份 PPT 缺的两张示意图。

  移动 P10 数据生命周期：说明数据从进来到消失，全程不出设备
  仓颉 P3  问题示意    ：说明"一个信号驱动三件事"为什么会错

为什么用图而不是文字：
  这两页要讲的是**结构与边界**，不是数值。
  文字描述"数据不出设备"是主张；画出来是设计。
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliverables" / "PPT材料" / "图表"


def setup():
    for name in ("Microsoft YaHei", "SimHei"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
        except Exception:
            continue
    return None


BLUE = "#0A59F7"
GREEN = "#0A8F4C"
RED = "#C0392B"
GREY = "#8A94A0"
CARD = "#F5F7FA"


def box(ax, x, y, w, h, text, fc=CARD, ec="#CCD3DB", fs=10.5, tc="#1F2328", bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.012",
                                facecolor=fc, edgecolor=ec, lw=1.2,
                                transform=ax.transAxes))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=tc, fontweight="bold" if bold else "normal", transform=ax.transAxes)


def arrow(ax, p1, p2, color=GREY, style="->", lw=1.6, ls="-"):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, color=color, lw=lw,
                                 linestyle=ls, mutation_scale=13,
                                 transform=ax.transAxes, shrinkA=2, shrinkB=2))


# ---------------------------------------------------------------------------
# 移动 P10：数据生命周期
# ---------------------------------------------------------------------------
def data_lifecycle():
    fig, ax = plt.subplots(figsize=(12, 5.4))
    ax.axis("off")

    # 标题放在边框之外，避免压住虚线
    ax.text(0.5, 0.985, "数据的全部生命周期 —— 从头到尾不离开这台设备",
            ha="center", va="top", fontsize=14.5, fontweight="bold", transform=ax.transAxes)

    # 设备边界（顶部留出标题空间）
    ax.add_patch(FancyBboxPatch((0.015, 0.075), 0.97, 0.855,
                                boxstyle="round,pad=0.004,rounding_size=0.012",
                                facecolor="none", edgecolor=BLUE, lw=2.0,
                                linestyle="--", transform=ax.transAxes))
    ax.text(0.030, 0.905, "这台设备（含应用私有沙箱）", fontsize=10,
            color=BLUE, fontweight="bold", va="top", transform=ax.transAxes)

    # 三个入口 - 每个只连一根箭头到沙箱
    entries = [
        ("粘贴文本", 0.04, 0.20, 0.375),
        ("相册选图\n（系统选择器）", 0.24, 0.40, 0.42),
        ("导入 txt / md\n（系统选择器）", 0.44, 0.60, 0.465),
    ]
    for label, x0, x1, tx in entries:
        box(ax, x0, 0.72, x1 - x0, 0.12, label, fc="#EAF1FE", ec="#B9D2FB", fs=10)
        arrow(ax, ((x0 + x1) / 2, 0.72), (tx, 0.635), color=BLUE)

    # 文字识别（只服务图片路径）
    box(ax, 0.625, 0.72, 0.20, 0.12, "文字识别\n（本地引擎）", fc="#EAF7F0", ec="#B7E1CC", fs=10)
    arrow(ax, (0.60, 0.78), (0.625, 0.78), color=BLUE)
    arrow(ax, (0.725, 0.72), (0.55, 0.635), color=BLUE)

    # 落盘
    box(ax, 0.29, 0.505, 0.30, 0.13, "应用私有沙箱\nlibrary.json",
        fc=CARD, ec="#CCD3DB", fs=11, bold=True)
    # 启动重建
    box(ax, 0.29, 0.315, 0.30, 0.12, "启动时重建索引\n（只存原文，不存索引）",
        fc=CARD, ec="#CCD3DB", fs=10)
    arrow(ax, (0.44, 0.505), (0.44, 0.435), color=GREY)
    # 检索
    box(ax, 0.29, 0.135, 0.30, 0.12, "在内存中检索\n结果不落盘", fc=CARD, ec="#CCD3DB", fs=10)
    arrow(ax, (0.44, 0.315), (0.44, 0.255), color=GREY)
    # 卸载
    box(ax, 0.705, 0.315, 0.25, 0.12, "卸载 → 全部删除\n不可恢复",
        fc="#FDECEA", ec="#F5B7B1", fs=10, tc=RED)
    arrow(ax, (0.59, 0.375), (0.705, 0.375), color=RED)

    ax.text(0.5, 0.032, "设备之外：没有服务器，没有账号，没有任何网络请求",
            ha="center", fontsize=11, color=RED, fontweight="bold", transform=ax.transAxes)

    p = OUT / "移动-P10-数据生命周期.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# 仓颉 P3：一个信号驱动三件事
# ---------------------------------------------------------------------------
def one_signal_problem():
    fig, ax = plt.subplots(figsize=(11.5, 5.0))
    ax.axis("off")

    ax.text(0.5, 0.965, "把三个维度压成一个信号，为什么会错",
            ha="center", fontsize=14.5, fontweight="bold", transform=ax.transAxes)

    # 左：单一信号
    box(ax, 0.04, 0.40, 0.20, 0.16, "剩余预算\n（一个标量）",
        fc="#FDECEA", ec="#F5B7B1", fs=11.5, tc=RED, bold=True)
    ax.text(0.14, 0.335, "常见做法", ha="center", fontsize=10, color=RED,
            transform=ax.transAxes)

    outs = [
        ("工具注入深度", "该看检索置信度", 0.72),
        ("消息表示形式", "该看可压缩空间", 0.47),
        ("执行放置位置", "该看网络状态", 0.22),
    ]
    for label, why, y in outs:
        box(ax, 0.52, y, 0.20, 0.14, label, fc=CARD, ec="#CCD3DB", fs=11)
        arrow(ax, (0.24, 0.48), (0.52, y + 0.07), color=RED, lw=1.8)
        ax.text(0.745, y + 0.07, why, fontsize=10, color=BLUE,
                va="center", fontweight="bold", transform=ax.transAxes)

    ax.text(0.04, 0.155, "三个维度的偏好方向经常相反：", fontsize=11,
            fontweight="bold", transform=ax.transAxes)
    ax.text(0.04, 0.105, "  预算充足时，仍可能没有可靠工具可注入（置信度低）", fontsize=10,
            transform=ax.transAxes)
    ax.text(0.04, 0.062, "  预算充足时，消息仍可能必须压缩（上下文窗口硬上限）", fontsize=10,
            transform=ax.transAxes)
    ax.text(0.04, 0.019, "  预算再大，离线时也只能本地执行", fontsize=10,
            transform=ax.transAxes)

    ax.text(0.52, 0.965, "", transform=ax.transAxes)
    ax.text(0.98, 0.50, "→ 一个标量驱动三件事\n   必然在某一维上做错",
            fontsize=11.5, color=GREEN, fontweight="bold", ha="right",
            va="center", transform=ax.transAxes)

    p = OUT / "仓颉-P3-一个信号的问题.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    f = setup()
    print("=" * 74)
    print("补充示意图")
    print("=" * 74)
    print(f"  中文字体: {f or '[未找到]'}")
    for name, fn in (("移动 P10 数据生命周期", data_lifecycle),
                     ("仓颉 P3 一个信号的问题", one_signal_problem)):
        try:
            p = fn()
            print(f"  [OK] {name:24} {p.name}  {p.stat().st_size:>7,} B")
        except Exception as e:
            print(f"  [失败] {name}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
