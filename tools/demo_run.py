#!/usr/bin/env python3
"""
Run the Cangjie-side demo and capture a real transcript.

WHY THIS EXISTS
    Both courses require demo material, and it was the only deliverable category
    with no actual output -- the shot list described what to record but nothing
    had been recorded. The Cangjie half needs no device and no model, so it can be
    demoed for real: every number below comes from the shipped binary, and the
    transcript is captured rather than transcribed by hand.

    Hand-transcribed demo output is exactly the kind of thing that drifts away
    from the code (see docs/07 for what that cost this project once already).

USAGE
    python tools/demo_run.py               # capture the transcript
    python tools/demo_run.py --show        # also print it to stdout
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "projects" / "agentbudget4cj" / "bin" / "agentbudget4cj.exe"
SCRATCH = ROOT / "experiments" / "_tmp"
OUTDIR = ROOT / "deliverables" / "演示素材"
OUT = OUTDIR / "仓颉演示实录.md"

TIERS = [("wifi", "wifi", 20, False, True),
         ("weak_lan", "weak", 1500, True, True),
         ("weak_nolan", "weak", 1500, True, False)]

QUERIES = [
    ("search my files for the quarterly report", "无歧义：一个工具明显胜出"),
    ("look up a contact named Li Wei in my address book", "轻微歧义"),
    ("find online the release notes for the new version", "零字面重叠：完全无信号"),
]


def run_engine(lines):
    """Drive the CLI in one process, returning its raw response lines."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    inp = SCRATCH / "demo_in.txt"
    outp = SCRATCH / "demo_out.txt"
    inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if outp.exists():
        outp.unlink()
    subprocess.run(f'cmd /c ""{ENGINE}" < "{inp}" > "{outp}" 2>&1"', shell=True, check=False)
    return [ln for ln in outp.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip() and not ln.startswith("ok\tpool=")]


def plan_lines(requests):
    return [f'{d} {tier} {rtt} {int(m)} {int(lan)} {spent} {cap} {cloud} {mode} {k} {q}'
            for (d, tier, rtt, m, lan, spent, cap, cloud, mode, k, q) in requests]


def section(title, body, block):
    return f"### {title}\n\n{body}\n\n```\n{block}\n```\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    if not ENGINE.exists():
        print(f"[demo] ERROR: engine not found at {ENGINE}")
        print("[demo] build it:  powershell -ExecutionPolicy Bypass -File tools\\cj.ps1 "
              "-Project agentbudget4cj bin")
        return 2

    parts = []
    parts.append("# 仓颉调度器演示实录\n")
    parts.append("> 本文件由 `tools/demo_run.py` **实际执行并捕获输出**生成，不是手工抄写。\n"
                 "> 重跑该脚本即可得到与本机一致的结果。\n")
    parts.append(f"> 引擎：`projects/agentbudget4cj/bin/agentbudget4cj.exe` "
                 f"（{ENGINE.stat().st_size:,} 字节）\n")

    # ---- 1. the decision ladder ----
    # Budget usage is kept at 75% deliberately: the scheduler only considers the
    # cloud while utilisation is below 80%, so a tighter budget would collapse all
    # three tiers onto the edge and hide the ladder this section exists to show.
    reqs = []
    for name, tier, rtt, m, lan in TIERS:
        reqs.append((0.8, tier, rtt, m, lan, 6000, 8000, 10, "budget", -50,
                     QUERIES[0][0]))
    out = run_engine(plan_lines(reqs))
    body = ("同一任务、同一预算（已用 75%），只改网络档位。三层各自显现：\n\n"
            "| 网络档 | 预期 | 依据 |\n|---|---|---|\n"
            "| wifi | cloud | 广域网可用 ∧ 难度≥0.6 ∧ 预算余量<80% |\n"
            "| weak_lan | **edge** | 广域网不可用，**但局域网边缘仍可达** |\n"
            "| weak_nolan | device | 既无广域网也无局域网 |\n\n"
            "**第 2 行是演示的关键**：把「广域网不可用」等同于「无远程选项」的基线\n"
            "会在这里全部退回设备，而调度器保住了边缘执行。\n")
    tbl = ["网络档         route      msgForm     toolStrategy      k   理由"]
    for name, r in zip([t[0] for t in TIERS], out):
        f = r.split("\t")
        reason = "\t".join(f[6:]) if len(f) > 6 else ""
        tbl.append(f"{name:<14} {f[0]:<10} {f[1]:<11} {f[2]:<17} {f[4]:>2}  {reason}")
    parts.append(section("1. 三层放置：降级方向保住边缘执行", body, "\n".join(tbl)))

    # ---- 2. adaptive k responds to ambiguity ----
    reqs = [(0.5, "wifi", 20, False, True, 7000, 8000, 10, "budget", -50, q)
            for q, _ in QUERIES]
    reqs.append((0.5, "wifi", 20, False, True, 4000, 8000, 10, "budget", -50, QUERIES[0][0]))
    reqs.append((0.5, "wifi", 20, False, True, 7900, 8000, 10, "budget", -50, QUERIES[0][0]))
    out = run_engine(plan_lines(reqs))
    tbl = ["查询                                          kUsed   选中工具"]
    for (q, note), r in zip(QUERIES, out[:3]):
        f = r.split("\t")
        tbl.append(f"{q[:44]:<44} {f[4]:>5}   {f[5][:40]}")
    tbl.append("")
    tbl.append("同一查询、不同预算（kUsed 应当不变）：")
    for spent, r in zip([7000, 4000, 7900], [out[0], out[3], out[4]]):
        f = r.split("\t")
        tbl.append(f"  预算已用 {spent:<6} -> kUsed={f[4]}")
    body = ("得分驱动的自适应策略：**对查询歧义敏感，对预算不敏感**。\n\n"
            "注意第 3 条查询——它与此前实验中「零字面重叠」的歧义查询相同，\n"
            "策略正确识别出信号缺失并回退到固定值。\n\n"
            "对照：把 k 绑定到 token 预算的版本在同一预算下会给所有查询**同一个 k**，\n"
            "且实测被每一个固定 k 支配。\n")
    parts.append(section("2. 自适应 top-k：信号来自检索，不是预算", body, "\n".join(tbl)))

    # ---- 3. selector comparison ----
    reqs = [(0.5, "wifi", 20, False, True, 7000, 8000, 10, "budget", k, QUERIES[0][0])
            for k in (-50, 0, 3, 5)]
    out = run_engine(plan_lines(reqs))
    labels = [("得分驱动（-50）", "本项目的提案"),
              ("预算驱动（0）", "负面结果：被固定 k 支配"),
              ("固定 k=3", "基线"),
              ("固定 k=5", "基线")]
    tbl = ["选择器                含义                         结果"]
    for (lab, note), r in zip(labels, out):
        f = r.split("\t")
        tbl.append(f"{lab:<20} {note:<28} {f[2]}  工具 tokens={f[3]}")
    body = ("同一查询、同一预算，只改选择器。\n\n"
            "这正是论文 §6.6->§6.7 的正负一对实验在命令行上的样子：\n"
            "预算驱动的策略看起来也「在工作」（给出了一个 k），但它实测被固定值支配；\n"
            "得分驱动的策略则在完整评测中支配了每一个固定 k。\n")
    parts.append(section("3. 三种选择器：为什么信号选错了就会输", body, "\n".join(tbl)))

    # ---- 4. message representation ----
    payload = '{"query": "quarterly report", "limit": 10}'
    reqs = [("natural", 40, "planner", "executor", "instruction", payload),
            ("summary", 40, "planner", "executor", "instruction", payload),
            ("structured", 40, "planner", "executor", "instruction", payload)]
    out = run_engine([f"codec|{f}|{b}|{a}|{c}|{i}|{p}" for f, b, a, c, i, p in reqs])
    tbl = ["形式          渲染结果                                                      token"]
    for (f, *_rest), r in zip(reqs, out):
        cols = r.split("\t")
        tbl.append(f"{f:<13} {cols[0][:60]:<60} {cols[1]:>4}")
    body = ("同一个负载，三种渲染。`structured` 最短且**无损**；\n"
            "`summary` 在 40 字符下截断了负载——这正是它在多跳链上必然失败的原因：\n"
            "第二条消息的载荷是第一条的回显，比第一条长约一倍，\n"
            "而定长前缀自己就吃掉了整个预算（论文 §3.3.1 给出跳数阈值公式）。\n")
    parts.append(section("4. 消息表示：结构化编码同时赢得成本与正确性", body, "\n".join(tbl)))

    # ---- 5. pool size ----
    reqs = [(0.55, "wifi", 20, False, True, 4400, 8000, 10, "budget", 3, QUERIES[0][0])]
    lines = ["pool|5"] + plan_lines(reqs) + ["pool|0"] + plan_lines(reqs)
    out = run_engine(lines)
    tbl = ["工具池   选中工具                                         工具 tokens"]
    for lab, r in zip(["5 个", "15 个"], out):
        f = r.split("\t")
        tbl.append(f"{lab:<9} {f[5][:48]:<48} {f[3]:>5}")
    body = ("`pool` 动词把工具池限制到前 N 个，使早期的 5 工具实验**可由命令复现**——\n"
            "而修复前的数据与修复后的数据**不可比较**。这一点曾导致论文一条核心结论出错\n"
            "（跨两套检索实现比较），详见 `docs/07`。\n")
    parts.append(section("5. 工具池规模：可复现性为什么是硬要求", body, "\n".join(tbl)))

    parts.append("## 复现\n\n```powershell\n"
                 "powershell -ExecutionPolicy Bypass -File tools\\cj.ps1 "
                 "-Project agentbudget4cj bin\n"
                 "python tools\\demo_run.py --show\n```\n")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(parts)
    OUT.write_text(text, encoding="utf-8")
    print(f"[demo] wrote {OUT}  ({len(text):,} chars)")
    if args.show:
        print()
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
