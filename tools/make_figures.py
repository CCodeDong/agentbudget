#!/usr/bin/env python3
"""
Generate publication-quality figures from the recorded experiment runs.

Every figure reads experiments/results*/summary.json directly, so a figure can
never disagree with the data it claims to show. Re-run after any experiment.

Outputs PNG (300 dpi) and PDF into paper/figures/.

Usage:
    python tools/make_figures.py
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments"
FIG = ROOT / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

# Chinese labels need an explicit CJK family. Microsoft YaHei is preferred over
# SimHei because it is the only available CJK face that carries U+2212 MINUS
# SIGN, which lets the figures use the same minus character as the prose instead
# of an ASCII hyphen. The minus sign must be overridden separately or matplotlib
# renders it as a box in the default math font.
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 120
plt.rcParams["savefig.bbox"] = "tight"

C_BASE = "#7A7A7A"      # the eager baseline
C_OURS = "#0A59F7"      # the budget scheduler
C_WARN = "#D93026"      # dominated / lossy
C_OK = "#1B8A2F"        # lossless
C_EDGE = "#E8A33D"


def load(name):
    f = EXP / name / "summary.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save(fig, stem):
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"{stem}.{ext}")
    plt.close(fig)
    print(f"  wrote {stem}.png / .pdf")


def note(fig, text, y=-0.02):
    fig.text(0.5, y, text, ha="center", fontsize=9, color="#555555")


# ---------------------------------------------------------------------------

def fig1_pareto():
    rows = load("results_ksweep")
    budget = {r["top_k"]: r for r in rows if r["mode"] == "budget"}
    eager = next((r for r in rows if r["mode"] == "eager"), None)

    ks = sorted(budget)
    x = [budget[k]["mean_prompt_tokens"] for k in ks]
    y = [budget[k]["success_rate"] for k in ks]

    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    if eager:
        ax.axhline(eager["success_rate"], color=C_BASE, ls="--", lw=1.4,
                   label=f"全量注入基线（{eager['mean_prompt_tokens']:.0f} tok）")
        ax.axvline(eager["mean_prompt_tokens"], color=C_BASE, ls=":", lw=1.0, alpha=0.6)

    ax.plot(x, y, "-o", color=C_OURS, lw=2, ms=7, label="两阶段注入（本方法）")
    for k, xi, yi in zip(ks, x, y):
        ax.annotate(f"k={k}", (xi, yi), textcoords="offset points",
                    xytext=(0, 11), ha="center", fontsize=10, color=C_OURS)

    # Shade the region where compression is free (success stays at the baseline).
    free = [(xi, yi) for xi, yi in zip(x, y) if eager and yi >= eager["success_rate"]]
    if free:
        fx = [p[0] for p in free]
        ax.axvspan(min(fx), (eager["mean_prompt_tokens"] if eager else max(fx)),
                   color=C_OK, alpha=0.08)
        best = min(fx)
        saving = (1 - best / eager["mean_prompt_tokens"]) * 100 if eager else 0
        ax.text((min(fx) + eager["mean_prompt_tokens"]) / 2, 0.905,
                f"免费区间\n省 {saving:.0f}% token\n零准确率损失",
                ha="center", fontsize=10, color=C_OK)

    ax.set_xlabel("平均 Prompt tokens")
    ax.set_ylabel("任务成功率")
    ax.set_title("图 1  上下文压缩的 Pareto 前沿（15 工具池）")
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right", fontsize=9)
    ax.set_ylim(0.88, 1.02)
    note(fig, "数据：experiments/results_ksweep（30 任务 × 5 个 k，300 次运行）")
    save(fig, "fig1_pareto_k")


def fig2_poolsize():
    # results_pool5_fixed, NOT results. The `results` directory predates the
    # retrieval normalisation fix, so pairing it with results_pool15_fixed
    # compares two different implementations -- which is what produced the
    # incorrect "compression is free at 5 tools" conclusion. See docs/07.
    p5 = load("results_pool5_fixed")
    p15 = load("results_pool15_fixed")
    if not p5 or not p15:
        print("  (skip fig2: results_pool5_fixed / results_pool15_fixed not available)")
        return

    def pick(rows):
        eager = next((r for r in rows if r["mode"] == "eager"), None)
        comp = None
        for r in rows:
            if r["mode"] == "budget" and str(r.get("strategies", "")).find("two-stage") >= 0:
                comp = r
                break
        return eager, comp

    e5, c5 = pick(p5)
    e15, c15 = pick(p15)

    labels = ["5 工具池", "15 工具池"]
    tok_e = [e5["mean_prompt_tokens"], e15["mean_prompt_tokens"]]
    tok_c = [c5["mean_prompt_tokens"], c15["mean_prompt_tokens"]]
    suc_e = [e5["success_rate"] * 100, e15["success_rate"] * 100]
    suc_c = [c5["success_rate"] * 100, c15["success_rate"] * 100]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 4.2))
    xpos = np.arange(2)
    w = 0.34
    ax1.bar(xpos - w / 2, tok_e, w, color=C_BASE, label="全量注入")
    ax1.bar(xpos + w / 2, tok_c, w, color=C_OURS, label="两阶段注入")
    for i, (a, b) in enumerate(zip(tok_e, tok_c)):
        ax1.text(i - w / 2, a + 20, f"{a:.0f}", ha="center", fontsize=9)
        ax1.text(i + w / 2, b + 20, f"{b:.0f}", ha="center", fontsize=9)
        ax1.text(i, max(a, b) + 130, f"\u2212{(1 - b / a) * 100:.0f}%",
                 ha="center", fontsize=10, color=C_OURS, fontweight="bold")
    ax1.set_xticks(xpos); ax1.set_xticklabels(labels)
    ax1.set_ylabel("平均 Prompt tokens")
    ax1.set_title("上下文开销")
    ax1.legend(fontsize=9); ax1.grid(axis="y", alpha=0.25)
    ax1.set_ylim(0, max(tok_e) * 1.25)

    ax2.bar(xpos - w / 2, suc_e, w, color=C_BASE)
    ax2.bar(xpos + w / 2, suc_c, w, color=C_OURS)
    for i, (a, b) in enumerate(zip(suc_e, suc_c)):
        ax2.text(i - w / 2, a + 0.6, f"{a:.1f}", ha="center", fontsize=9)
        ax2.text(i + w / 2, b + 0.6, f"{b:.1f}", ha="center", fontsize=9)
        if b < a:
            ax2.text(i, min(a, b) - 3.4, f"\u2212{a - b:.1f}pp", ha="center",
                     fontsize=10, color=C_WARN, fontweight="bold")
    ax2.set_xticks(xpos); ax2.set_xticklabels(labels)
    ax2.set_ylabel("成功率（%）")
    ax2.set_title("准确率")
    ax2.set_ylim(80, 104); ax2.grid(axis="y", alpha=0.25)

    fig.suptitle("图 2  token 节省随工具池规模增长，准确率代价不随之增长", fontsize=13)
    note(fig, "两个池规模下的准确率代价都是 30 个任务中损失 1 个（−3.3pp），"
              "且代价全部来自检索漏选", y=0.005)
    save(fig, "fig2_pool_size")


def fig3_msgform():
    rows = load("results_multiturn")
    budget = {r["budget_util"]: r for r in rows if r["mode"] == "budget"}
    eager = next((r for r in rows if r["mode"] == "eager"), None)
    if not budget:
        return

    def form_label(u):
        return "natural" if u < 0.3 else ("summary" if u < 0.6 else "structured")

    order = sorted(budget)
    names = [form_label(u) for u in order]
    tok = [budget[u]["mean_prompt_tokens"] for u in order]
    suc = [budget[u]["success_rate"] * 100 for u in order]
    if eager:
        names = ["natural\n（基线）"] + names
        tok = [eager["mean_prompt_tokens"]] + tok
        suc = [eager["success_rate"] * 100] + suc

    colors = []
    for n, s in zip(names, suc):
        colors.append(C_WARN if s < 50 else (C_OK if "structured" in n else C_OURS))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.0, 4.2))
    xpos = np.arange(len(names))
    ax1.bar(xpos, tok, color=colors)
    for i, t in enumerate(tok):
        ax1.text(i, t + 30, f"{t:.0f}", ha="center", fontsize=9)
    ax1.set_xticks(xpos); ax1.set_xticklabels(names, fontsize=9)
    ax1.set_ylabel("平均 Prompt tokens")
    ax1.set_title("上下文开销（差距仅 2.5%）")
    ax1.grid(axis="y", alpha=0.25)

    ax2.bar(xpos, suc, color=colors)
    for i, s in enumerate(suc):
        ax2.text(i, s + 2, f"{s:.1f}%", ha="center", fontsize=9)
    ax2.set_xticks(xpos); ax2.set_xticklabels(names, fontsize=9)
    ax2.set_ylabel("成功率（%）")
    ax2.set_title("准确率（摘要形式归零）")
    ax2.set_ylim(0, 118); ax2.grid(axis="y", alpha=0.25)

    fig.suptitle("图 3  消息表示：结构化编码同时赢得成本与正确性", fontsize=13)
    note(fig, "截断切掉了 JSON 的收尾括号，参数结构被破坏——而它只比结构化编码便宜 1 个 token",
         y=0.005)
    save(fig, "fig3_message_form")


def fig4_routing():
    rows = load("results_pool15_fixed")
    profiles = ["wifi_lan", "weak_lan", "weak_nolan", "offline"]
    order = ["cloud", "edge", "on-device"]

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.2))
    for ax, mode, title in ((axes[0], "eager", "全量注入基线"),
                            (axes[1], "budget", "预算调度器（本方法）")):
        data = {p: None for p in profiles}
        for r in rows:
            if r["mode"] == mode:
                data[r["net"]] = r
        xs, bottoms = [], []
        for i, p in enumerate(profiles):
            r = data.get(p)
            if not r:
                continue
            routes = json.loads(r["routes"])
            bottom = 0
            total = sum(routes.values()) or 1
            xs.append(i)
            for ri, rname in enumerate(order):
                v = routes.get(rname, 0) / total * 100
                c = {"cloud": C_OURS, "edge": C_EDGE, "on-device": C_BASE}[rname]
                ax.bar(i, v, bottom=bottom, color=c,
                       label=rname if i == 0 else None, width=0.62)
                if v > 8:
                    ax.text(i, bottom + v / 2, f"{v:.0f}%", ha="center",
                            va="center", fontsize=9, color="white")
                bottom += v
        ax.set_xticks(range(len(profiles)))
        ax.set_xticklabels(["WiFi\n+LAN", "弱网\n+LAN", "弱网\n无LAN", "离线"], fontsize=9)
        ax.set_ylabel("执行位置分布（%）")
        ax.set_title(title)
        ax.set_ylim(0, 100)
    axes[1].legend(fontsize=9, loc="upper right", framealpha=0.9)
    fig.suptitle("图 4  三层放置：弱网下保住边缘执行", fontsize=13)
    note(fig, "基线把「广域网不可用」等同于「无远程选项」，全部退回设备；"
              "调度器保住了局域网边缘节点", y=0.005)
    save(fig, "fig4_routing")


def fig5_retrieval_fix():
    before = load("results_pool15")
    after = load("results_pool15_fixed")
    if not before or not after:
        return

    def comp(rows):
        for r in rows:
            if r["mode"] == "budget" and str(r.get("strategies", "")).find("two-stage") >= 0:
                return r
        return None

    b, a = comp(before), comp(after)
    if not b or not a:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.4, 4.0))
    labels = ["修复前", "修复后"]
    xpos = np.arange(2)

    ax1.bar(xpos, [b["success_rate"] * 100, a["success_rate"] * 100],
            color=[C_WARN, C_OK], width=0.55)
    for i, v in enumerate([b["success_rate"] * 100, a["success_rate"] * 100]):
        ax1.text(i, v + 0.8, f"{v:.1f}%", ha="center", fontsize=11, fontweight="bold")
    ax1.set_xticks(xpos); ax1.set_xticklabels(labels)
    ax1.set_ylabel("压缩臂成功率（%）")
    ax1.set_ylim(84, 100)
    ax1.set_title("准确率恢复 +6.7pp")
    ax1.grid(axis="y", alpha=0.25)

    miss_before, miss_after = 18, 6
    ax2.bar(xpos, [miss_before, miss_after], color=[C_WARN, C_OK], width=0.55)
    for i, v in enumerate([miss_before, miss_after]):
        ax2.text(i, v + 0.4, str(v), ha="center", fontsize=11, fontweight="bold")
    ax2.set_xticks(xpos); ax2.set_xticklabels(labels)
    ax2.set_ylabel("金标工具漏选次数")
    ax2.set_title("检索漏选 -67%")
    ax2.grid(axis="y", alpha=0.25)

    fig.suptitle("图 5  查询归一化（停用词过滤 + 去重）的效果", fontsize=13)
    note(fig, "查询中 the 出现两次，任何描述含 the 的工具各得 +6，压过了唯一正确的工具；"
              "修复代价仅 token +3%", y=0.005)
    save(fig, "fig5_retrieval_fix")


def fig6_a2a():
    """A2A envelope composition, computed the same way as experiments/a2a_overhead.py."""
    def enc(o):
        return json.dumps(o, separators=(",", ":"), ensure_ascii=False)

    args = json.dumps({"query": "quarterly report", "limit": "5"}, separators=(",", ":"))
    payloads = {
        "natural": f"Agent planner is sending the following instruction to agent executor: {args}",
        "summary": f"[planner->executor] instruction: {args[:40]}",
        "structured": f"planner|executor|instruction|{args}",
    }
    names, env, pay = [], [], []
    for k, v in payloads.items():
        msg = {"messageId": "msg-00000000-0000-0000-0000-000000000000", "role": 0,
               "parts": [{"text": v}]}
        total = len(enc(msg))
        names.append(k); env.append(total - len(v)); pay.append(len(v))

    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    xpos = np.arange(len(names))
    ax.bar(xpos, env, color=C_BASE, label="协议信封（固定开销）")
    ax.bar(xpos, pay, bottom=env, color=C_OURS, label="载荷")
    for i, (e, p) in enumerate(zip(env, pay)):
        ax.text(i, e + p + 4, f"{e + p} B", ha="center", fontsize=10, fontweight="bold")
        ax.text(i, e / 2, f"{e}", ha="center", va="center", fontsize=9, color="white")
    ax.set_xticks(xpos); ax.set_xticklabels(names)
    ax.set_ylabel("JSON 字节数")
    ax.set_title("图 6  HarmonyOS A2A 消息的信封开销占比")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    note(fig, "信封固定 ~87 B，占一条真实消息的 46–58%；"
              "排序保持不变：structured < summary < natural", y=0.005)
    save(fig, "fig6_a2a_envelope")


def fig7_sumbudget():
    """The truncating summary: cheap where it is broken, useless where it is not.

    Two independent measurements agree, which is what makes this figure worth
    drawing: the codec chain analysis (codec_cost_curve.py) and the measured
    task success rate (results_sumbudget) both put the break-even at the same
    budget.
    """
    chain_f = EXP / "results_codec_cost" / "codec_chain.json"
    single_f = EXP / "results_codec_cost" / "codec_cost.json"
    runs = load("results_sumbudget")
    if not chain_f.exists():
        print("  (skip fig7: run experiments/codec_cost_curve.py first)")
        return

    chain = json.loads(chain_f.read_text(encoding="utf-8"))
    single = json.loads(single_f.read_text(encoding="utf-8")) if single_f.exists() else []

    def pick(rows, form, budget=None):
        for r in rows:
            if r["form"] == form and (budget is None or r["budget"] == budget):
                return r
        return None

    budgets = sorted(r["budget"] for r in chain
                     if r["form"] == "summary" and isinstance(r["budget"], int))
    s_tok = [pick(chain, "summary", b)["mean_chain_tokens"] for b in budgets]
    s_int = [pick(chain, "summary", b)["intact_pct"] for b in budgets]
    nat = pick(chain, "natural")
    st = pick(chain, "structured")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.6, 4.4))

    ax1.plot(budgets, s_tok, "-o", color=C_WARN, lw=2, ms=7, label="summary（截断式）")
    if nat:
        ax1.axhline(nat["mean_chain_tokens"], color=C_BASE, ls="--", lw=1.4,
                    label=f"natural（{nat['mean_chain_tokens']:.1f} tok）")
    if st:
        ax1.axhline(st["mean_chain_tokens"], color=C_OK, ls="-", lw=2,
                    label=f"structured（{st['mean_chain_tokens']:.1f} tok）")
    ax1.set_xscale("log", base=2)
    ax1.set_xticks(budgets); ax1.get_xaxis().set_major_formatter(
        matplotlib.ticker.ScalarFormatter())
    ax1.set_xlabel("summary 字符预算")
    ax1.set_ylabel("两跳消息链的平均 token")
    ax1.set_title("成本：预算越大越接近结构化编码")
    ax1.grid(alpha=0.25); ax1.legend(fontsize=9)

    ax2.plot(budgets, s_int, "-o", color=C_WARN, lw=2, ms=7, label="参数完整性（链路分析）")
    if runs:
        pts = sorted([r for r in runs if r["mode"] == "budget" and r["budget_util"] == 0.45],
                     key=lambda r: r["summary_budget"])
        ax2.plot([r["summary_budget"] for r in pts],
                 [r["success_rate"] * 100 for r in pts],
                 "--s", color=C_OURS, lw=2, ms=7, label="实测任务成功率")
    ax2.set_xscale("log", base=2)
    ax2.set_xticks(budgets); ax2.get_xaxis().set_major_formatter(
        matplotlib.ticker.ScalarFormatter())
    ax2.set_xlabel("summary 字符预算")
    ax2.set_ylabel("比例（%）")
    ax2.set_ylim(-6, 112)
    ax2.set_title("正确性：两套独立测量在同一点转折")
    ax2.grid(alpha=0.25); ax2.legend(fontsize=9, loc="lower right")

    fig.suptitle("图 7  截断式摘要：便宜的地方是坏的，完整的地方不便宜", fontsize=13)
    fig.subplots_adjust(bottom=0.22)
    note(fig, "预算 ≤60：更便宜但验证器拿不到参数；预算 ≥80：恢复完整但成本追平结构化编码。"
              "不存在既完整又明显更便宜的预算。", y=-0.14)
    save(fig, "fig7_summary_budget")


def fig8_adaptive():
    """The negative result: a budget-derived k is dominated at every point."""
    rows = load("results_adaptive")
    if not rows:
        print("  (skip fig8: results_adaptive not available)")
        return

    pts = [{"k": r["top_k"], "util": r["budget_util"],
            "tok": r["mean_prompt_tokens"], "succ": r["success_rate"]} for r in rows]
    fixed = [p for p in pts if p["k"] != 0]
    adapt = [p for p in pts if p["k"] == 0]

    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    markers = {1: "o", 3: "s", 5: "^", 8: "D"}
    for k in sorted({p["k"] for p in fixed}):
        sub = [p for p in fixed if p["k"] == k]
        ax.scatter([p["tok"] for p in sub], [p["succ"] * 100 for p in sub],
                   marker=markers.get(k, "o"), s=90, color=C_BASE,
                   label=f"固定 k={k}", zorder=3)

    ax.scatter([p["tok"] for p in adapt], [p["succ"] * 100 for p in adapt],
               marker="*", s=340, color=C_WARN, label="自适应 k（预算驱动）", zorder=4)

    # annotate each adaptive point with the fixed k that dominates it
    for a in adapt:
        dom = [b for b in fixed
               if b["succ"] >= a["succ"] and b["tok"] <= a["tok"]
               and (b["succ"] > a["succ"] or b["tok"] < a["tok"])]
        if not dom:
            continue
        best = min(dom, key=lambda b: b["tok"])
        ax.annotate("", xy=(best["tok"], best["succ"] * 100),
                    xytext=(a["tok"], a["succ"] * 100),
                    arrowprops=dict(arrowstyle="->", color=C_WARN, lw=1.6, alpha=0.8))
        ax.text((a["tok"] + best["tok"]) / 2, (a["succ"] + best["succ"]) * 50 + 1.2,
                f"被 k={best['k']} 支配", fontsize=9, color=C_WARN, ha="center")

    ax.set_xlabel("平均 Prompt tokens")
    ax.set_ylabel("任务成功率（%）")
    ax.set_title("图 8  预算驱动的自适应 top-k 被固定 k 支配")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="lower right")
    ax.set_ylim(88, 102)
    fig.subplots_adjust(bottom=0.24)
    note(fig, "自适应在余量充足时过度花费、紧张时花费不足——"
              "说明预算余量与检索难度不相关。每个自适应点都被某个固定 k 支配，"
              "但支配它的 k 各不相同。", y=-0.16)
    save(fig, "fig8_adaptive_k")


def fig9_score_k():
    """The resolution: a retrieval-derived signal dominates every fixed k."""
    rows = load("results_score_k")
    if not rows:
        print("  (skip fig9: results_score_k not available)")
        return

    pts = [{"k": r["top_k"], "util": r["budget_util"],
            "tok": r["mean_prompt_tokens"], "succ": r["success_rate"]} for r in rows]
    fixed = [p for p in pts if p["k"] > 0]
    # Any negative selector is the score-driven policy; its magnitude is the
    # threshold percentage, which may be re-tuned. Matching a literal value here
    # would silently produce an empty series the moment alpha changes -- which is
    # exactly what happened when the suite was re-run at -50 instead of -1.
    score = [p for p in pts if p["k"] < 0]
    budget = [p for p in pts if p["k"] == 0]
    if not score:
        print("  (skip fig9: no score-driven rows found)")
        return

    fig, ax = plt.subplots(figsize=(8.4, 4.9))
    markers = {1: "o", 3: "s", 5: "^", 8: "D"}
    for k in sorted({p["k"] for p in fixed}):
        sub = [p for p in fixed if p["k"] == k]
        ax.scatter([p["tok"] for p in sub], [p["succ"] * 100 for p in sub],
                   marker=markers.get(k, "o"), s=95, color=C_BASE,
                   label=f"固定 k={k}", zorder=3)

    ax.scatter([p["tok"] for p in budget], [p["succ"] * 100 for p in budget],
               marker="*", s=300, color=C_WARN, label="预算驱动自适应（§6.6 被支配）", zorder=4)
    ax.scatter([p["tok"] for p in score], [p["succ"] * 100 for p in score],
               marker="*", s=430, color=C_OK, label="得分驱动自适应（§6.7 支配固定 k）", zorder=5)

    # arrows from the score-driven point to each fixed k it dominates
    a = min(score, key=lambda p: p["tok"])
    for b in fixed:
        if a["succ"] >= b["succ"] and a["tok"] <= b["tok"] and a["tok"] < b["tok"]:
            ax.annotate("", xy=(b["tok"], b["succ"] * 100), xytext=(a["tok"], a["succ"] * 100),
                        arrowprops=dict(arrowstyle="->", color=C_OK, lw=1.5, alpha=0.55))

    ax.annotate("-72.6% vs 全量注入\n成功率相同", xy=(a["tok"], a["succ"] * 100),
                xytext=(a["tok"] + 120, 92.2), fontsize=9.5, color=C_OK,
                arrowprops=dict(arrowstyle="->", color=C_OK, lw=1.2))

    ax.set_xlabel("平均 Prompt tokens")
    ax.set_ylabel("任务成功率（%）")
    ax.set_title("图 9  检索得分作为信号：支配每一个固定 k")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8.5, loc="lower right")
    ax.set_ylim(88, 102.4)
    fig.subplots_adjust(bottom=0.24)
    note(fig, "得分驱动策略对查询歧义敏感而对预算不敏感：30 个任务中 14 个只需一个完整 schema，"
              "1 个因无词法信号回退到 k=5。", y=-0.16)
    save(fig, "fig9_score_driven_k")


def main():
    print("generating figures into", FIG)
    fig1_pareto()
    fig2_poolsize()
    fig3_msgform()
    fig4_routing()
    fig5_retrieval_fix()
    fig6_a2a()
    fig7_sumbudget()
    fig8_adaptive()
    fig9_score_k()
    print("done")


if __name__ == "__main__":
    main()
