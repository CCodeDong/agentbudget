#!/usr/bin/env python3
"""
Reproduce the paper's experiment suite from a single command.

WHY THIS EXISTS
    The reproducibility statement was spread across a dozen design documents, each
    naming the arguments for one suite. That is both hard to audit and easy to
    drift: after top-k was parameterised so that negative values encode a
    threshold percentage, the recorded command `--ks=-1` silently stopped
    meaning what it meant when the data was produced (it now selects a 1%
    threshold, not the 50% the results were measured at).

    So the suite declarations live here, in one place, and the script CHECKS them
    against the result directories that already exist. Drift in either direction
    -- a changed command, or results regenerated under a different grid -- is
    reported rather than discovered later.

MODES
    --check     verify the declared suites match the results on disk (no running)
    --grids     print the declared grid for every suite and exit
    --run       execute the suites (needs the mock endpoint; started here)
    --manifest  write results/MANIFEST.json describing environment and outputs

USAGE
    python tools/reproduce.py --check
    python tools/reproduce.py --run results_multiturn results_score_k
    python tools/reproduce.py --run --all
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The console may be a legacy code page (GBK here) while child processes emit
# UTF-8 that decodes to replacement characters. Printing those raw crashes the
# tool at the very moment it is trying to report a failure, which is the worst
# possible time to lose the diagnostic. Force a lossy UTF-8 stream instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments"
MOCK = EXP / "mock_llm_server.py"
MOCK_URL = "http://127.0.0.1:8100"

# ---------------------------------------------------------------------------
# Suite declarations. Each entry is the exact command that produced the results
# directory named by `out`.
#
# `expect` records the grid the suite is supposed to cover, so `--check` can
# compare it with what is actually on disk. `runs` is the expected number of
# loop runs; a mismatch means the suite did not cover the grid it claims.
#
# TRAP: the --nets ARGUMENT takes profile keys (wifi, weak_lan, ...) but the
# summary records the resolved LABEL, and the wifi profile records as "wifi_lan"
# because it has LAN reachability. So args say `wifi` while expect says
# `wifi_lan`. Mixing the two fails at runtime with KeyError, which is exactly
# what the first draft of this table did.
# ---------------------------------------------------------------------------

SUITES = [
    {
        "out": "results_pool15_fixed",
        "why": "§6.1/§6.3 — pool-size contrast and placement on the corrected "
               "retrieval (the run before the stopword fix is kept separately)",
        "args": ["--modes", "eager,budget", "--nets", "wifi,weak_lan,weak_nolan",
                 "--utils", "0.25,0.55,0.85"],
        "expect": {"mode": ["budget", "eager"],
                   "net": ["weak_lan", "weak_nolan", "wifi_lan"],
                   "budget_util": [0.25, 0.55, 0.85]},
        "runs": 540,
    },
    {
        "out": "results_ksweep",
        "why": "§6.2 — the free compression region (top-k sweep)",
        "args": ["--modes", "eager,budget", "--nets", "wifi", "--utils", "0.85",
                 "--ks", "1,2,3,5,8"],
        "expect": {"mode": ["budget", "eager"], "net": ["wifi_lan"],
                   "budget_util": [0.85], "top_k": [1, 2, 3, 5, 8]},
        "runs": 300,
    },
    {
        "out": "results_multiturn",
        "why": "§6.4 — message representation in the three-agent loop",
        "args": ["--multiturn", "--modes", "eager,budget", "--nets", "wifi",
                 "--utils", "0.1,0.45,0.85", "--ks", "3"],
        "expect": {"mode": ["budget", "eager"], "net": ["wifi_lan"],
                   "budget_util": [0.1, 0.45, 0.85], "top_k": [3]},
        "runs": 180,
    },
    {
        "out": "results_sumbudget",
        "why": "§6.4 — truncation-budget sensitivity",
        "args": ["--multiturn", "--modes", "budget", "--nets", "wifi",
                 "--utils", "0.45,0.85", "--ks", "3",
                 "--summary-budgets", "20,40,80,160,320"],
        "expect": {"mode": ["budget"], "net": ["wifi_lan"],
                   "budget_util": [0.45, 0.85], "top_k": [3],
                   "summary_budget": [20, 40, 80, 160, 320]},
        "runs": 300,
    },
    {
        "out": "results_adaptive",
        "why": "§6.6 — the NEGATIVE result: a budget-derived k is dominated",
        "args": ["--multiturn", "--modes", "budget", "--nets", "wifi",
                 "--utils", "0.6,0.75,0.9", "--ks", "0,1,3,5,8"],
        "expect": {"mode": ["budget"], "net": ["wifi_lan"],
                   "budget_util": [0.6, 0.75, 0.9], "top_k": [0, 1, 3, 5, 8],
                   "summary_budget": [40]},
        "runs": 450,
    },
    {
        "out": "results_score_k",
        "why": "§6.7 — the resolution: a retrieval-derived k dominates every fixed k",
        # NOTE -50, not -1. Negative selectors encode the threshold as a
        # percentage of the top score; -1 would mean a 1% threshold, which is a
        # different policy from the one the recorded data was produced under.
        "args": ["--multiturn", "--modes", "budget", "--nets", "wifi",
                 "--utils", "0.6,0.75,0.9", "--ks", "-50,0,1,3,5,8"],
        "expect": {"mode": ["budget"], "net": ["wifi_lan"],
                   "budget_util": [0.6, 0.75, 0.9],
                   "top_k": [-50, 0, 1, 3, 5, 8], "summary_budget": [40]},
        "runs": 540,
    },
    {
        "out": "results_pool5_fixed",
        "why": "§6.1/§6.3 — the five-tool pool under the CURRENT retrieval. "
               "Regenerated after it was found that pairing the pre-fix five-tool "
               "run with the post-fix fifteen-tool run manufactured a contrast "
               "that does not exist (see docs/07).",
        "args": ["--pool", "5", "--modes", "eager,budget",
                 "--nets", "wifi,weak_lan,weak_nolan", "--utils", "0.25,0.55,0.85"],
        "expect": {"mode": ["budget", "eager"],
                   "net": ["weak_lan", "weak_nolan", "wifi_lan"],
                   "budget_util": [0.25, 0.55, 0.85]},
        "runs": 540,
    },
    {
        "out": "results_smoke",
        "why": "plumbing smoke test (3 tasks per profile)",
        "args": ["--limit", "3"],
        "expect": {"mode": ["budget", "eager"],
                   "net": ["weak_lan", "weak_nolan", "wifi_lan"]},
        "runs": 18,
    },
    {
        "out": "results_mt_smoke",
        "why": "multi-turn plumbing smoke test (2 tasks per profile)",
        "args": ["--multiturn", "--nets", "wifi", "--utils", "0.1,0.45,0.85",
                 "--ks", "3", "--limit", "2"],
        "expect": {"mode": ["budget", "eager"], "net": ["wifi_lan"],
                   "budget_util": [0.1, 0.45, 0.85], "top_k": [3]},
        "runs": 12,
    },
    {
        "out": "results",
        "why": "SUPERSEDED — the original five-tool run, produced before the "
               "retrieval normalisation fix. Kept as the record of that defect, "
               "but it must never be compared against results_pool15_fixed.",
        "args": None,
        "historical": True,
        "expect": {"mode": ["budget", "eager"],
                   "net": ["weak_lan", "weak_nolan", "wifi_lan"],
                   "budget_util": [0.25, 0.55, 0.85]},
        "runs": 540,
    },
    {
        "out": "results_pool15",
        "why": "SUPERSEDED — the fifteen-tool run before the retrieval fix; this "
               "is the evidence for the stopword defect (k=3 gave 0.900).",
        "args": None,
        "historical": True,
        "expect": {"mode": ["budget", "eager"],
                   "net": ["weak_lan", "weak_nolan", "wifi_lan"],
                   "budget_util": [0.25, 0.55, 0.85]},
        "runs": 540,
    },
]

# Non-harness artefacts that are part of the reproduction but need no endpoint.
DERIVED = [
    ("codec chain analysis (no model)", [sys.executable, str(EXP / "codec_cost_curve.py")]),
    ("token estimator audit", [sys.executable, str(EXP / "token_estimator_audit.py")]),
    ("figures", [sys.executable, str(ROOT / "tools" / "make_figures.py")]),
    ("paper cross-reference check", [sys.executable, str(ROOT / "tools" / "check_paper.py")]),
    ("app/library consistency", [sys.executable, str(ROOT / "tools" / "verify_app_logic.py")]),
]


def grid_of(out_dir: Path):
    """Recover the effective grid recorded by a suite's summary.json."""
    f = out_dir / "summary.json"
    if not f.exists():
        return None, None
    rows = json.loads(f.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        return None, None
    grid = {}
    for r in rows:
        for k in ("mode", "net", "budget_util", "top_k", "summary_budget"):
            if k in r:
                grid.setdefault(k, set()).add(r[k])
    grid = {k: sorted(v) for k, v in grid.items()}
    runs = sum(r.get("runs", 0) for r in rows)
    return grid, runs


def do_check():
    print("=" * 78)
    print("SUITE DECLARATION vs RESULTS ON DISK")
    print("=" * 78)
    problems = 0
    for s in SUITES:
        out_dir = EXP / s["out"]
        grid, runs = grid_of(out_dir)
        print(f"\n{s['out']}")
        if grid is None:
            print("  MISSING: no summary.json (run it, or the path is wrong)")
            problems += 1
            continue
        ok = True
        for k, want in s["expect"].items():
            got = grid.get(k)
            if got != want:
                print(f"  {k:<16} declared {want}")
                print(f"  {'':<16} on disk  {got}   <- MISMATCH")
                ok = False
        if runs != s["runs"]:
            print(f"  runs             declared {s['runs']}, on disk {runs}   <- MISMATCH")
            ok = False
        if ok:
            tag = ("HISTORICAL - superseded, kept as a record, NOT reproducible"
                   if s.get("historical") else "reproducible")
            print(f"  OK  grid matches, {runs} runs  [{tag}]")
        else:
            problems += 1
    print()
    if problems:
        print(f"[reproduce] {problems} suite(s) drifted from their declaration")
        return 1
    print("[reproduce] all suites match their declarations")
    return 0


def preflight():
    print("=" * 78)
    print("PREFLIGHT")
    print("=" * 78)
    ok = True
    print(f"  python           {sys.version.split()[0]} ({platform.system()} {platform.release()})")
    for mod in ("numpy", "pandas", "matplotlib"):
        try:
            m = __import__(mod)
            print(f"  {mod:<16} {getattr(m, '__version__', '?')}")
        except ImportError:
            print(f"  {mod:<16} MISSING")
            ok = False
    print(f"  mock endpoint    {'present' if MOCK.exists() else 'MISSING'}")
    engine = ROOT / "projects" / "agentbudget4cj" / "bin" / "agentbudget4cj.exe"
    if engine.exists():
        print(f"  cangjie engine   {engine.stat().st_size:,} B")
    else:
        print("  cangjie engine   MISSING (run tools/cj.ps1 -Project agentbudget4cj bin)")
        ok = False
    print()
    return ok


def wait_for_mock(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{MOCK_URL}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def run_suites(names, all_suites):
    chosen = SUITES if all_suites else [s for s in SUITES if s["out"] in names]
    if not chosen:
        print("[reproduce] no suites selected")
        return 1

    print("[reproduce] starting the mock endpoint ...")
    mock = subprocess.Popen([sys.executable, str(MOCK), "--port", "8100",
                             "--decode-ms-per-token", "1.5"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for_mock():
            print("[reproduce] ERROR: mock endpoint did not become healthy")
            return 1
        print("[reproduce] endpoint is up")
        for s in chosen:
            cmd = [sys.executable, str(EXP / "experiment.py"), *s["args"],
                   "--out", s["out"]]
            print(f"\n[reproduce] {s['out']}: {s['why']}")
            print(f"[reproduce] {' '.join(cmd[1:])}")
            r = subprocess.run(cmd, cwd=str(EXP), capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            log = EXP / (s["out"] + ".run.log")
            log.write_text((r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or ""),
                           encoding="utf-8")
            tail = [ln for ln in r.stdout.splitlines() if ln.startswith("[harness]")]
            for ln in tail:
                print("   ", ln)
            if r.returncode != 0:
                print(f"[reproduce] FAILED (exit {r.returncode})")
                print(f"[reproduce] full output written to {log}")
                err_lines = [ln for ln in (r.stderr or "").splitlines() if ln.strip()]
                for ln in err_lines[-12:]:
                    print("   !", ln)
                return 1
    finally:
        mock.terminate()
        try:
            mock.wait(timeout=10)
        except subprocess.TimeoutExpired:
            mock.kill()
        print("\n[reproduce] endpoint stopped")

    print("\n[reproduce] running derived artefacts")
    for label, cmd in DERIVED:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        status = "ok" if r.returncode == 0 else f"FAILED ({r.returncode})"
        print(f"    {label:<34} {status}")
    return 0


def sha256(p: Path):
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def write_manifest():
    man = {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "suites": [],
        "derived": [],
    }
    for s in SUITES:
        d = EXP / s["out"]
        rows = json.loads((d / "summary.json").read_text(encoding="utf-8")) \
            if (d / "summary.json").exists() else []
        man["suites"].append({
            "out": s["out"],
            "why": s["why"],
            "args": s["args"],
            "historical": bool(s.get("historical")),
            "runs": sum(r.get("runs", 0) for r in rows),
            "runs_csv_sha256_16": sha256(d / "runs.csv") if (d / "runs.csv").exists() else None,
        })
    for name in ("results_codec_cost",):
        pass
    for label, _ in DERIVED:
        man["derived"].append({"label": label})

    figs = ROOT / "paper" / "figures"
    man["figures"] = [{"name": p.name, "sha256_16": sha256(p)}
                      for p in sorted(figs.glob("*.png"))]
    man["total_runs"] = sum(s["runs"] for s in man["suites"])

    out = EXP / "MANIFEST.json"
    out.write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[reproduce] wrote {out}")
    print(f"[reproduce] total loop runs across declared suites: {man['total_runs']}")
    print(f"[reproduce] figures hashed: {len(man['figures'])}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="verify declared suites against results on disk")
    ap.add_argument("--grids", action="store_true", help="print the declared grids")
    ap.add_argument("--run", nargs="*", metavar="SUITE", help="run the named suites")
    ap.add_argument("--all", action="store_true", help="with --run: run every suite")
    ap.add_argument("--manifest", action="store_true", help="write results/MANIFEST.json")
    args = ap.parse_args()

    if args.grids:
        for s in SUITES:
            print(f"{s['out']:<24} runs={s['runs']:<5} " +
                  " ".join(f"{k}={v}" for k, v in s["expect"].items()))
        return 0
    if args.check:
        return do_check()
    if args.manifest:
        return write_manifest()
    if args.run is not None:
        if not preflight():
            print("[reproduce] preflight failed")
            return 1
        return run_suites(set(args.run), args.all)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
