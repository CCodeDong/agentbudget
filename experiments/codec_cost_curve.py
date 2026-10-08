#!/usr/bin/env python3
"""
Codec cost curve: what each message representation costs, on the real payloads.

WHY THIS EXISTS
    The multi-agent harness ties the message form to budget utilisation, so it
    cannot compare `summary` and `structured` at the SAME tool-context size. The
    first sweep therefore showed only that a large enough truncation budget
    restores success -- it did not show whether `summary` ever beats
    `structured`.

    This script isolates the codec dimension. It takes the actual tool-call
    payloads the planner produces for the task set, renders each with every
    representation and every truncation budget THROUGH THE CANGJIE CODEC, and
    reports token cost and whether the payload survives intact.

    That yields the precise claim the data supports:
      * below payload length, truncation breaks the payload;
      * above it, truncation is a no-op whose cost converges to (and does not
        beat) the structured form.
    Either way there is no budget at which the truncating summary is a good
    choice -- but the reason differs, and the report must say which.

Usage:
    python experiments/codec_cost_curve.py
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXE = ROOT / "projects" / "agentbudget4cj" / "bin" / "agentbudget4cj.exe"
SCRATCH = HERE / "_tmp"

sys.path.insert(0, str(HERE))
from experiment import TASKS, TOOLS  # noqa: E402

BUDGETS = [20, 40, 60, 80, 120, 160, 320]


def payloads():
    """Reproduce the planner's argument payload for each task.

    Mirrors AgentRuntime / the mock planner: the chosen tool's declared
    parameters, each filled with a placeholder derived from the name.
    """
    by_name = {t["name"]: t for t in TOOLS}
    out = []
    for task in TASKS:
        tool = by_name[task["gold_tool"]]
        args = {p: f"<{p} from task>" for p in tool["params"]}
        out.append((task["id"], json.dumps(args)))
    return out


def codec_batch(requests):
    """requests: list of (form, budget, from, to, intent, payload)."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    inp = SCRATCH / "cost_in.txt"
    outp = SCRATCH / "cost_out.txt"
    lines = [f"codec|{f}|{b}|{fr}|{to}|{i}|{p}" for f, b, fr, to, i, p in requests]
    inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if outp.exists():
        outp.unlink()
    subprocess.run(f'cmd /c ""{EXE}" < "{inp}" > "{outp}" 2>&1"', shell=True, check=False)
    res = []
    for line in outp.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            res.append(("", 0))
        else:
            res.append((parts[0], int(parts[1]) if parts[1].isdigit() else 0))
    if len(res) != len(requests):
        raise RuntimeError(f"codec returned {len(res)} for {len(requests)} requests")
    return res


def main():
    if not EXE.exists():
        print(f"engine not found: {EXE}")
        return 1

    pl = payloads()
    n = len(pl)
    print(f"payloads: {n}  (mean length {sum(len(p) for _, p in pl) / n:.1f} chars)")
    print()

    # ---- per-form cost ----
    rows = []
    for form, budget in (("natural", 40), ("structured", 40)) + tuple(
            ("summary", b) for b in BUDGETS):
        reqs = [(form, budget, "planner", "executor", "instruction", p) for _, p in pl]
        res = codec_batch(reqs)
        toks = [t for _, t in res]
        # A payload survives iff the rendered message still contains every
        # parameter name the verifier will look for.
        intact = 0
        for (tid, p), (rendered, _) in zip(pl, res):
            names = json.loads(p).keys()
            if all(k in rendered for k in names):
                intact += 1
        rows.append({
            "form": form, "budget": budget if form == "summary" else "-",
            "mean_tokens": round(sum(toks) / len(toks), 2),
            "intact": intact, "intact_pct": round(100 * intact / n, 1),
        })

    print(f"{'form':<11} {'budget':>6} {'mean tok':>9} {'intact':>8} {'intact %':>9}")
    print("-" * 48)
    for r in rows:
        print(f"{r['form']:<11} {str(r['budget']):>6} {r['mean_tokens']:>9.2f} "
              f"{r['intact']:>4}/{n:<3} {r['intact_pct']:>8.1f}%")

    out = HERE / "results_codec_cost"
    out.mkdir(exist_ok=True)
    (out / "codec_cost.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    print(f"\nwrote {out / 'codec_cost.json'}")

    # ---- the claim that the data actually supports ----
    natural = next(r for r in rows if r["form"] == "natural")
    structured = next(r for r in rows if r["form"] == "structured")
    # ---- the message CHAIN: why a budget that is fine for message 1 fails ----
    #
    # The harness renders message 2 from the EXECUTOR'S OUTPUT, which already
    # contains the rendered message 1. So the second payload is roughly twice as
    # long as the first, and the fixed-length prefix of the summary rendering
    # consumes the entire budget before any tool argument name appears.
    print("\nMESSAGE CHAIN (planner->executor->verifier)")
    chain_requests = []
    for form, budget in (("natural", 40), ("structured", 40)) + tuple(
            ("summary", b) for b in BUDGETS):
        for _, p in pl:
            chain_requests.append((form, budget, p))
    # render message 1 for every (form, budget, payload)
    m1_reqs = [(f, b, "planner", "executor", "instruction", p) for f, b, p in chain_requests]
    m1 = codec_batch(m1_reqs)
    # the executor echoes what it received, exactly as the mock does
    exec_out = ["EXECUTED: " + r for r, _ in m1]
    m2_reqs = [(f, b, "executor", "verifier", "result", eo)
               for (f, b, _), eo in zip(chain_requests, exec_out)]
    m2 = codec_batch(m2_reqs)

    agg = {}
    for (f, b, p), (_, t1), (r2, t2) in zip(chain_requests, m1, m2):
        key = (f, b if f == "summary" else "-")
        names = list(json.loads(p).keys())
        ok = all(nm in r2 for nm in names)
        a = agg.setdefault(key, {"n": 0, "intact": 0, "tok": 0})
        a["n"] += 1
        a["intact"] += 1 if ok else 0
        a["tok"] += t1 + t2

    print(f"  {'form':<11} {'budget':>6} {'chain tok':>10} {'verifier sees args':>19}")
    print("  " + "-" * 50)
    chain_rows = []
    for key in sorted(agg, key=lambda k: (k[0], str(k[1]))):
        a = agg[key]
        pctv = 100 * a["intact"] / a["n"]
        print(f"  {key[0]:<11} {str(key[1]):>6} {a['tok'] / a['n']:>10.2f} "
              f"{a['intact']:>7}/{a['n']:<3} ({pctv:>5.1f}%)")
        chain_rows.append({"form": key[0], "budget": key[1],
                           "mean_chain_tokens": round(a["tok"] / a["n"], 2),
                           "intact_pct": round(pctv, 1)})
    (out / "codec_chain.json").write_text(
        json.dumps(chain_rows, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nINTERPRETATION")
    print(f"  natural    : {natural['mean_tokens']:.2f} tok, intact {natural['intact_pct']:.0f}%")
    print(f"  structured : {structured['mean_tokens']:.2f} tok, intact {structured['intact_pct']:.0f}%"
          f"  (saves {(1 - structured['mean_tokens'] / natural['mean_tokens']) * 100:.1f}% vs natural)")
    print("  summary by budget:")
    for r in rows:
        if r["form"] != "summary":
            continue
        vs_nat = (1 - r["mean_tokens"] / natural["mean_tokens"]) * 100
        flag = "BROKEN" if r["intact_pct"] < 100 else "intact"
        verdict = ("dominated (broken payload)" if flag == "BROKEN"
                   else ("dominated (costs >= structured, adds nothing)"
                         if r["mean_tokens"] >= structured["mean_tokens"] else "?? beats structured"))
        print(f"    budget {r['budget']:>3}: {r['mean_tokens']:>7.2f} tok "
              f"(saves {vs_nat:>4.1f}% vs natural)  {flag:<7} -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
