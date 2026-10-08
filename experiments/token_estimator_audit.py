#!/usr/bin/env python3
"""
Audit the token estimators the project relies on.

WHY THIS EXISTS
    Every token number in the paper is produced by a heuristic, and there was
    more than one of them:

      * the Cangjie library estimates tokens as `ascii_bytes/4 + (wide_bytes+2)/3`
        and uses that to make scheduling decisions;
      * the mock endpoint reports `len(prompt) // 4`, i.e. four characters per
        token regardless of script, and THAT is what the harness records as
        `prompt_tokens`.

    So the reported numbers and the decisions that produced them came from two
    different estimators. That is a construct-validity defect: the paper's
    central claim is a ratio between two token counts, and neither count is a
    real tokenizer's.

    This script quantifies the gap against a real BPE tokenizer and reports
    whether the headline conclusions survive.

Usage:
    python experiments/token_estimator_audit.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from experiment import TOOLS, TASKS, build_system_prompt  # noqa: E402


# ---------------------------------------------------------------------------
# the two heuristics actually used in the project
# ---------------------------------------------------------------------------

def mock_tokens(prompt: str) -> int:
    """What mock_llm_server.py reports as prompt_tokens."""
    return max(1, len(prompt) // 4)


def cangjie_tokens(prompt: str) -> int:
    """What the Cangjie library's estimateTokens() computes (byte based)."""
    raw = prompt.encode("utf-8")
    ascii_b = sum(1 for b in raw if b < 128)
    wide_b = len(raw) - ascii_b
    return ascii_b // 4 + (wide_b + 2) // 3


# ---------------------------------------------------------------------------
# a real tokenizer, if one can be obtained
# ---------------------------------------------------------------------------

def real_tokenizer():
    """Return (name, fn) for a real BPE tokenizer, or (None, None)."""
    try:
        import tiktoken
        for enc_name in ("o200k_base", "cl100k_base"):
            try:
                enc = tiktoken.get_encoding(enc_name)
                return f"tiktoken:{enc_name}", (lambda s, e=enc: len(e.encode(s)))
            except Exception:
                continue
    except ImportError:
        pass
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained("gpt2")
        return "hf:gpt2", (lambda s, t=tok: len(t.encode(s)))
    except Exception:
        pass
    return None, None


def main():
    enc_name, enc_fn = real_tokenizer()
    print("=" * 78)
    print("TOKEN ESTIMATOR AUDIT")
    print("=" * 78)
    print(f"real tokenizer : {enc_name or 'NOT AVAILABLE (network or package missing)'}")
    print()

    # Reconstruct the exact prompts the harness assembles: the summary lines are
    # always present, and only the number of FULL_SCHEMA blocks varies.
    utterance = TASKS[0]["utterance"]
    names = [t["name"] for t in TOOLS]

    rows = []
    for k in [0, 1, 2, 3, 5, 8, len(names)]:
        selected = names[:k] if k else []
        mode = "eager" if k == len(names) else "budget"
        prompt = build_system_prompt(selected, mode)
        rows.append({
            "k": k if k != len(names) else "all",
            "chars": len(prompt),
            "mock": mock_tokens(prompt),
            "cangjie": cangjie_tokens(prompt),
            "real": enc_fn(prompt) if enc_fn else None,
        })

    hdr = f"{'k':>4} {'chars':>7} {'mock(len/4)':>12} {'cangjie':>9} {'real':>7} {'mock err':>9} {'cangjie err':>12}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if r["real"]:
            me = f"{(r['mock'] / r['real'] - 1) * 100:+.1f}%"
            ce = f"{(r['cangjie'] / r['real'] - 1) * 100:+.1f}%"
        else:
            me = ce = "-"
        print(f"{str(r['k']):>4} {r['chars']:>7} {r['mock']:>12} {r['cangjie']:>9} "
              f"{str(r['real'] or '-'):>7} {me:>9} {ce:>12}")

    # ---- does the headline ratio survive? ----
    eager = next(r for r in rows if r["k"] == "all")
    print()
    print("=" * 78)
    print("DOES THE HEADLINE SURVIVE?  (context reduction of the compressed arm)")
    print("=" * 78)
    print(f"{'estimator':<16} {'eager':>8} {'top-1':>8} {'top-3':>8} {'top-5':>8}   reduction vs eager (top-1 / top-3)")
    print("-" * 94)
    for key, label in (("mock", "mock(len//4)"), ("cangjie", "cangjie"), ("real", "real BPE")):
        if key != "mock" and eager[key] is None:
            continue
        e = eager[key]
        t1 = next((r[key] for r in rows if r["k"] == 1), None)
        t3 = next((r[key] for r in rows if r["k"] == 3), None)
        t5 = next((r[key] for r in rows if r["k"] == 5), None)
        if e and t1 and t3:
            print(f"{label:<16} {e:>8} {t1:>8} {t3:>8} {str(t5 or '-'):>8}   "
                  f"{(1 - t1 / e) * 100:>6.1f}% / {(1 - t3 / e) * 100:>5.1f}%")

    # ---- the specific question the paper answers ----
    if enc_fn:
        print()
        print("=" * 78)
        print("RATIO CONSISTENCY")
        print("=" * 78)
        for a, b in ((1, "all"), (3, "all"), (5, "all")):
            ra = next(r for r in rows if r["k"] == a)
            rb = next(r for r in rows if r["k"] == b)
            rm = ra["mock"] / rb["mock"]
            rr = ra["real"] / rb["real"]
            rc = ra["cangjie"] / rb["cangjie"]
            print(f"  top-{a} / all : mock {rm:.3f}   cangjie {rc:.3f}   real {rr:.3f}   "
                  f"-> mock error {(rm / rr - 1) * 100:+.1f}pp, cangjie error {(rc / rr - 1) * 100:+.1f}pp")

    # ---- the two heuristics coincide ONLY because the workload is ASCII ----
    print()
    print("=" * 78)
    print("WHEN DO THE ESTIMATORS DIVERGE?  (script mix matters)")
    print("=" * 78)
    cases = [
        ("pure ASCII (this project)", "search my files for the quarterly report draft"),
        ("mixed ASCII + CJK", "search my files for the 季度报告 draft"),
        ("pure CJK", "帮我搜索关于季度报告的文档并总结要点"),
    ]
    hdr2 = f"{'case':<28} {'len//4':>7} {'byte-weighted':>14} {'ratio':>8}"
    print(hdr2)
    print("-" * len(hdr2))
    for name, s in cases:
        m, c = mock_tokens(s), cangjie_tokens(s)
        print(f"{name:<28} {m:>7} {c:>14} {c / m:>7.2f}x")
    print()
    print("  -> identical on this project's workload (all prompts are ASCII),")
    print("     so no reported token number is affected by the earlier mismatch.")
    print("  -> up to 4.5x apart on pure CJK, which a Chinese-language")
    print("     deployment would hit immediately. Hence the single definition.")

    print()
    print("NOTE: the reductions below are computed from a SINGLE representative")
    print("prompt, so they are indicative rather than a re-measurement of the")
    print("experiments. A full re-run is needed to restate any reported number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
