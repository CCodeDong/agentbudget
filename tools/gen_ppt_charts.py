#!/usr/bin/env python3
"""
生成两份立项 PPT 需要的图表。

WHY CHARTS INSTEAD OF TABLES ON SLIDES
    投影时表格字号必须很小才放得下，最后一排看不清。
    同一组数据做成图，一眼能看出方向；具体数字放在讲稿或附录页。

数据来源（全部来自本仓库，不手填）：
    移动应用 P6/P7  -> projects/offlinelib-core 的评估输出（本文档内联，已复现过）
    移动应用 P8     -> deliverables/演示素材/L7 OCR质量测试/L7验证记录.md 的实测表
    仓颉     P8     -> experiments/results*/summary.csv（11 套件 / 3,960 次运行）
"""

import csv
import glob
import os
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliverables" / "PPT材料" / "图表"


def setup_font():
    """中文字体：不设置的话所有汉字都是方块。"""
    for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 移动应用 P6：固定 k vs 自适应
# ---------------------------------------------------------------------------
# 数据来自 `python tools/olib.py eval` 的实测输出（150 条查询，61 份文档 / 2,277 片段）
FIXED_K3 = {"召回率": 100.0, "精确率": 62.0, "平均返回": 3.0, "MRR": 0.970}
ADAPTIVE = {"召回率": 100.0, "精确率": 84.7, "平均返回": 1.9, "MRR": 0.970}


def chart_search_strategy():
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    metrics = [("精确率", "%"), ("平均返回", "条"), ("召回率", "%")]
    for ax, (m, unit) in zip(axes, metrics):
        a, b = FIXED_K3[m], ADAPTIVE[m]
        bars = ax.bar(["固定 k=3", "自适应"], [a, b], color=["#9AA5B1", "#0A59F7"], width=0.55)
        for r, v in zip(bars, [a, b]):
            ax.text(r.get_x() + r.get_width() / 2, v, f"{v:g}{unit}",
                    ha="center", va="bottom", fontsize=11, fontweight="bold")
        ax.set_title("平均返回条数" if m == "平均返回" else m, fontsize=12, fontweight="bold")
        top = max(a, b) * 1.28 if max(a, b) else 1
        ax.set_ylim(0, top)
        ax.set_yticks([])
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="x", labelsize=10.5)
    fig.suptitle("150 条真实语料查询：同样的召回，更少的噪音", fontsize=13.5, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = OUT / "移动-P6-检索策略对比.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# 移动应用 P7：去重效果
# ---------------------------------------------------------------------------
def chart_dedup():
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    vals = [35, 11]
    bars = ax.bar(["未合并", "合并相邻块"], vals, color=["#9AA5B1", "#0A8F4C"], width=0.5)
    for r, v in zip(bars, vals):
        ax.text(r.get_x() + r.get_width() / 2, v, str(v),
                ha="center", va="bottom", fontsize=14, fontweight="bold")
    ax.annotate("", xy=(1, 11), xytext=(0, 35),
                arrowprops=dict(arrowstyle="->", color="#C0392B", lw=2))
    ax.text(0.5, 26, "-69%", ha="center", fontsize=15,
            fontweight="bold", color="#C0392B")
    ax.set_ylabel("出现「同一文档重复返回」的查询数", fontsize=11)
    ax.set_ylim(0, 42)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("合并后：重复展示减少 69%，召回率与 MRR 不变",
                 fontsize=12.5, fontweight="bold")
    fig.tight_layout()
    p = OUT / "移动-P7-去重效果.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# 移动应用 P8：12 种退化
# ---------------------------------------------------------------------------
OCR_CASES = [
    ("清晰（基准）", 100, 100), ("高斯模糊", 100, 100), ("低对比", 100, 100),
    ("旋转 6.5°", 100, 100), ("小字号", 100, 100), ("楷体", 100, 100),
    ("极低对比", 100, 100), ("旋转 15°", 100, 100), ("噪声", 100, 100),
    ("行楷（近手写）", 98, 98), ("强模糊", 93, 93), ("小字 + 模糊", 28, 100),
]


def chart_ocr_quality():
    labels = [c[0] for c in OCR_CASES]
    recall = [c[1] for c in OCR_CASES]
    prec = [c[2] for c in OCR_CASES]
    y = range(len(labels))

    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    h = 0.38
    ax.barh([i + h / 2 for i in y], prec, height=h, color="#0A8F4C", label="精确率")
    ax.barh([i - h / 2 for i in y], recall, height=h, color="#0A59F7", label="召回率")
    for i, (r, p) in enumerate(zip(recall, prec)):
        ax.text(r + 1.2, i - h / 2, f"{r}%", va="center", fontsize=9)
        ax.text(p + 1.2, i + h / 2, f"{p}%", va="center", fontsize=9, color="#0A8F4C")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 118)
    ax.set_xlabel("百分比", fontsize=10.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", fontsize=10, frameon=False)
    ax.set_title("12 种退化条件：精确率从不低于召回率\n最差的一档是「漏认」而不是「错认」",
                 fontsize=12.5, fontweight="bold")
    ax.axvline(100, color="#CCCCCC", ls=":", lw=1)
    fig.tight_layout()
    p = OUT / "移动-P8-OCR退化实测.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# 仓颉 P8：budget vs eager
# ---------------------------------------------------------------------------
def chart_cangjie():
    """
    仓颉 P8：正反实验 —— 但**按套件分开画，不做跨套件平均**。

    WHY 不聚合
        我第一版把 results / pool15 / multiturn 三个套件按预算档位平均，
        得到一条"0.45 档成功率掉到 0、0.85 档回到 97%"的折线。
        那条线是**假象**：三个套件的任务池难度不同（5 工具 / 15 工具 / 多轮），
        混在一起平均，等于把不同实验的条件当成同一个条件的多次测量。

        分开看才看得见真实结论：
          · 成本显著下降（token 降 50–70%）—— 这在所有套件上都成立
          · 成功率多数持平或略降（90–100%）
          · **但在 0.45 这一档、多轮任务下，本方案成功率跌到 0%** —— 这是真实缺陷

        所以图要做成两栏：左成本、右成功率，且分别标出用的是哪个套件。
    """
    def load(suite):
        p = ROOT / "experiments" / suite / "summary.csv"
        if not p.exists():
            return {}
        out = {}
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    bu = float(r["budget_util"]); runs = int(r["runs"])
                    sr = float(r["success_rate"]); tk = float(r["mean_prompt_tokens"])
                except (ValueError, KeyError):
                    continue
                d = out.setdefault(r["mode"], {}).setdefault(bu, [0, 0.0, 0.0])
                d[0] += runs
                d[1] += sr * runs
                d[2] += tk * runs
        res = {}
        for mode, budgets in out.items():
            res[mode] = {b: (v[1] / v[0] * 100, v[2] / v[0]) for b, v in budgets.items()}
        return res

    cost_suite = load("results_pool15")      # 15 工具，成本对比最清楚
    succ_suite = load("results_multiturn")   # 多轮，暴露 0.45 档的问题

    colors = {"budget": "#0A59F7", "eager": "#C0392B"}
    names = {"budget": "按维度各自信号（本方案）", "eager": "一次性全注入（基线）"}

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.2))

    ax = axes[0]
    bs = sorted(cost_suite.get("budget", {}))
    for mode in ("budget", "eager"):
        d = cost_suite.get(mode, {})
        ys = [d[b][1] if b in d else None for b in bs]
        ax.plot(bs, ys, "o-", color=colors[mode], label=names[mode], lw=2, ms=6)
    ax.set_xlabel("预算档位（budget_util）", fontsize=11)
    ax.set_ylabel("平均 prompt tokens", fontsize=11)
    ax.set_title("成本：每一档都更低（15 工具套件）", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9.5, frameon=False)
    ax.grid(alpha=0.25)
    ax.annotate("约 -68%", xy=(0.7, 600), fontsize=12, fontweight="bold", color="#0A8F4C")

    ax = axes[1]
    bs2 = sorted(succ_suite.get("budget", {}))
    for mode in ("budget", "eager"):
        d = succ_suite.get(mode, {})
        ys = [d[b][0] if b in d else None for b in bs2]
        ax.plot(bs2, ys, "o-", color=colors[mode], label=names[mode], lw=2, ms=6)
    ax.set_xlabel("预算档位（budget_util）", fontsize=11)
    ax.set_ylabel("任务成功率（%）", fontsize=11)
    ax.set_title("成功率：0.45 档本方案跌到 0（多轮套件）", fontsize=12, fontweight="bold")
    ax.set_ylim(-6, 108)
    ax.legend(fontsize=9.5, frameon=False, loc="lower right")
    ax.grid(alpha=0.25)
    ax.annotate("待定位的缺陷", xy=(0.45, 0), xytext=(0.5, 32),
                fontsize=10.5, color="#C0392B", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#C0392B", lw=1.6))

    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    p = OUT / "仓颉-P8-正反实验.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ---------------------------------------------------------------------------
# 仓颉 P6：进展统计卡
# ---------------------------------------------------------------------------
def chart_progress():
    stats = [("源文件", "8", "个"), ("代码", "1,678", "行"), ("单元测试", "29", "个"),
             ("行覆盖", "88.6", "%"), ("实验套件", "11", "个"), ("逐次运行", "3,960", "次")]
    fig, ax = plt.subplots(figsize=(11, 2.0))
    ax.axis("off")
    for i, (label, value, unit) in enumerate(stats):
        x = i / len(stats)
        ax.add_patch(plt.Rectangle((x + 0.008, 0.08), 0.975 / len(stats), 0.84,
                                   transform=ax.transAxes, facecolor="#F5F7FA",
                                   edgecolor="#DDE3EA", lw=1))
        ax.text(x + 0.008 + 0.4875 / len(stats), 0.62, value,
                ha="center", va="center", fontsize=20, fontweight="bold",
                color="#0A59F7", transform=ax.transAxes)
        ax.text(x + 0.008 + 0.4875 / len(stats), 0.58, unit,
                ha="center", va="top", fontsize=9, color="#666666",
                transform=ax.transAxes)
        ax.text(x + 0.008 + 0.4875 / len(stats), 0.26, label,
                ha="center", va="center", fontsize=10.5,
                transform=ax.transAxes)
    p = OUT / "仓颉-P6-进展统计.png"
    fig.savefig(p, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    f = setup_font()
    print("=" * 74)
    print("生成 PPT 图表")
    print("=" * 74)
    print(f"  中文字体: {f or '[未找到，汉字会变方块]'}")
    print("")

    jobs = [
        ("移动应用 P6 检索策略对比", chart_search_strategy),
        ("移动应用 P7 去重效果", chart_dedup),
        ("移动应用 P8 OCR 退化实测", chart_ocr_quality),
        ("仓颉 P6 进展统计", chart_progress),
        ("仓颉 P8 正反实验", chart_cangjie),
    ]
    for name, fn in jobs:
        try:
            p = fn()
            print(f"  [OK] {name:26} {p.name}  {p.stat().st_size:>7,} B")
        except Exception as e:
            print(f"  [失败] {name}: {type(e).__name__}: {e}")
    print("")
    print(f"  输出目录：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
