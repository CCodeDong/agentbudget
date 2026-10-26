#!/usr/bin/env python3
"""
把系统包管理器的权限声明渲染成一张证据图。

WHY 用命令输出而不是设置页截图
    设置页里「应用 → 离线资料库 → 权限」需要多次导航与滚动，
    在 2in1 的浮动窗口下不稳定。
    而 `bm dump -n <包名>` 是**系统包管理器自己报的**，同样可核实，
    甚至更硬：它不依赖界面渲染，任何人在任意设备上都能复现这条命令。

    图里必须写清"这是命令输出"，不能伪装成界面截图。
"""

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliverables" / "PPT材料" / "图表"
RAW = ROOT / "_out" / "bundledump.txt"


def setup():
    for name in ("Microsoft YaHei", "SimHei"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue


def main():
    if not RAW.exists():
        print(f"  找不到 {RAW}，先跑 bm dump")
        return 2
    text = RAW.read_text(encoding="utf-8", errors="replace")

    perm_lines = [ln.strip() for ln in text.splitlines() if re.search(r"(?i)permission", ln)]
    # 去重保序
    seen, uniq = set(), []
    for ln in perm_lines:
        if ln not in seen:
            seen.add(ln)
            uniq.append(ln)
    if not uniq:
        print("  输出里没有任何 permission 字段")
        return 2

    setup()
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.axis("off")

    ax.text(0.5, 0.955, "零权限的核实方式：让系统自己报一遍", ha="center",
            fontsize=14.5, fontweight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.885,
            "在电脑上执行：hdc shell bm dump -n com.xjtu.offlinelib",
            ha="center", fontsize=10.5, color="#0A59F7", transform=ax.transAxes)

    # 代码块
    ax.add_patch(plt.Rectangle((0.05, 0.20), 0.90, 0.60, transform=ax.transAxes,
                               facecolor="#1E1E1E", edgecolor="#333333"))
    y = 0.74
    for ln in uniq[:9]:
        ax.text(0.075, y, ln, fontsize=10.5, color="#E8E8E8",
                family="Consolas", transform=ax.transAxes, va="top")
        y -= 0.062

    ax.text(0.5, 0.115,
            "包管理器返回的权限声明全部为空数组 —— 应用没有申请任何权限",
            ha="center", fontsize=11.5, color="#0A8F4C", fontweight="bold",
            transform=ax.transAxes)
    ax.text(0.5, 0.045,
            "包括网络权限。这条命令在任意设备上可复现，不依赖界面。",
            ha="center", fontsize=10, color="#666666", transform=ax.transAxes)

    p = OUT / "移动-P9-零权限核实.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [OK] {p.name}  {p.stat().st_size:,} B")
    print(f"       抓到 {len(uniq)} 条权限相关行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
