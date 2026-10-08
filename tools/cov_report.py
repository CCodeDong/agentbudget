#!/usr/bin/env python3
"""
Read cjcov's HTML report and print the real coverage numbers.

WHY THIS EXISTS
    cjcov emits an HTML report whose layout is easy to misread: each row is
    separated by blank cells, and the Branches column is literally "-" unless
    `--branches` was passed. Reading it by eye is how this project came to record
    a per-file LINE figure (router.cj 63.0%) as project branch coverage, and a
    single file's line coverage (budget.cj 89.6%) as the project total. Both
    numbers were wrong by wide margins and sat in the report for a long time.

    Parsing it mechanically removes that failure mode.

    It also separates the library from the CLI and benchmark harnesses. `main.cj`
    is never touched by unit tests, so including it drags the total down in a way
    that says nothing about the decision logic; excluding it silently would hide
    real untested code. Both numbers are reported.

USAGE
    python tools/cov_report.py            # human-readable table
    python tools/cov_report.py --json     # machine-readable
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "projects" / "agentbudget4cj" / "_out" / "coverage_html" / "coverage_html" / "index.html"
# Older runs wrote the report one level up; accept either.
ALT = ROOT / "projects" / "agentbudget4cj" / "_out" / "coverage_html" / "index.html"

EXCLUDE_FROM_LIBRARY = ("main.cj", "bench.cj", "_test.cj")


def parse(report: Path):
    text = report.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>", "", text, flags=re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "|", text)
    lines = [re.sub(r"\|+", "|", ln).strip("| \t")
             for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    try:
        start = lines.index("File")
    except ValueError:
        return None, None

    seg = lines[start:]
    files = []
    k = 0
    while k < len(seg):
        if seg[k].endswith(".cj"):
            # Take the next four non-empty cells. Do NOT assume a fixed stride:
            # cjcov's table has been observed both with and without blank filler
            # cells between rows, and a fixed stride silently misaligns names
            # with numbers -- which is the same class of error this tool exists
            # to prevent.
            cells = []
            j = k + 1
            while j < len(seg) and len(cells) < 4:
                if seg[j].strip():
                    cells.append(seg[j])
                j += 1
            if len(cells) == 4:
                files.append({
                    "file": seg[k],
                    "lines": cells[0], "lines_pct": cells[1],
                    "branches": cells[2], "branches_pct": cells[3],
                })
            k = j
        else:
            k += 1

    def frac(s):
        try:
            a, b = s.split("/")
            return int(a), int(b)
        except Exception:
            return 0, 0

    def total(rows):
        lh = lt = bh = bt = 0
        for r in rows:
            a, b = frac(r["lines"]); lh += a; lt += b
            c, d = frac(r["branches"]); bh += c; bt += d
        return {
            "lines_hit": lh, "lines_total": lt,
            "lines_pct": round(100 * lh / lt, 1) if lt else 0.0,
            "branches_hit": bh, "branches_total": bt,
            "branches_pct": round(100 * bh / bt, 1) if bt else 0.0,
        }

    lib = [r for r in files if not any(x in r["file"] for x in EXCLUDE_FROM_LIBRARY)]
    return files, {"all": total(files), "library": total(lib),
                   "excluded": [r["file"] for r in files if r not in lib]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = REPORT if REPORT.exists() else ALT
    if not report.exists():
        print(f"[cov] no report at {REPORT}")
        print("[cov] run: powershell -ExecutionPolicy Bypass -File tools\\cj.ps1 "
              "-Project agentbudget4cj cover")
        return 2

    files, summary = parse(report)
    if files is None:
        print("[cov] could not parse the report layout")
        return 2

    if args.json:
        print(json.dumps({"report": str(report), "files": files, "summary": summary},
                         indent=2, ensure_ascii=False))
        return 0

    print(f"[cov] {report}")
    print()
    print(f"  {'file':<24} {'lines':>10} {'%':>8} {'branches':>10} {'%':>8}")
    print("  " + "-" * 64)
    for r in files:
        print(f"  {r['file']:<24} {r['lines']:>10} {r['lines_pct']:>8} "
              f"{r['branches']:>10} {r['branches_pct']:>8}")
    print("  " + "-" * 64)
    for label in ("all", "library"):
        s = summary[label]
        name = "TOTAL (all files)" if label == "all" else "LIBRARY ONLY"
        print(f"  {name:<24} {s['lines_hit']:>4}/{s['lines_total']:<5} "
              f"{s['lines_pct']:>7.1f}% {s['branches_hit']:>4}/{s['branches_total']:<5} "
              f"{s['branches_pct']:>7.1f}%")
    print()
    print(f"  excluded from LIBRARY ONLY: {', '.join(summary['excluded'])}")
    print("  (the CLI is exercised by the demo and every experiment, just not"
          " by unit tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
