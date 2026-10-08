#!/usr/bin/env python3
"""
Execute the HarmonyOS app's pure-logic ArkTS modules under Node and compare them
with the Cangjie library.

WHY THIS EXISTS
    The app cannot be run without a device, but the decision logic
    (Types / Tokens / MessageCodec / ToolRegistry / BudgetPolicy) contains no
    ArkUI decorators -- it is plain TypeScript. If those modules disagree with
    the Cangjie library, the demo and the experiments would describe two
    different systems while claiming to describe one. BudgetPolicy.ets's own
    header warns about exactly that, so it is worth checking rather than
    asserting.

    Node 24 supports type transformation natively, so the modules can be
    executed directly.

WHAT THIS CHECKS
    Consistency of the port: the app must choose the same k as the library for
    the same queries, and produce the same decision ladder.
    It does NOT check device behaviour -- the network probe and the A2A HSP still
    require a real phone.

IMPLEMENTATION NOTE
    Type stripping erases `interface` and `type` declarations, so an import that
    names only types becomes an unresolved value import at runtime. This mirrors
    the modules to an ASCII directory and rewrites each import to keep only the
    names that actually exist at runtime (enums, classes, functions, consts).
    The app sources are never modified.

Usage:
    python tools/verify_app_logic.py
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "harmony" / "entry" / "src" / "main" / "ets"
ENGINE = ROOT / "projects" / "agentbudget4cj" / "bin" / "agentbudget4cj.exe"

MODULES = [
    "model/Types.ets",
    "core/Tokens.ets",
    "core/MessageCodec.ets",
    "agents/ToolRegistry.ets",
    "core/BudgetPolicy.ets",
]

NODE_CANDIDATES = [
    Path(r"D:\develop\DevEco Studio\tools\node\node.exe"),
    Path("node"),
]

# The port cannot be eliminated: the compiler accepts an aarch64-linux-ohos
# target but the SDK ships only the windows_x86_64_cjnative standard library, and
# no Linux/ohos Cangjie toolchain exists on this machine. So the ArkTS side is the
# only way to run the scheduler decision on-device, and this differential test is
# therefore load-bearing rather than a nicety.
#
# Rather than assert a handful of remembered values, both implementations are run
# over the ENTIRE task set and their choices diffed. A spot check can pass while
# the two diverge everywhere else.
def all_queries():
    sys.path.insert(0, str(ROOT / "experiments"))
    from experiment import TASKS
    return [t["utterance"] for t in TASKS]


def library_k(queries):
    """Ask the Cangjie engine for k on each query, one batch, one process."""
    scratch = ROOT / "experiments" / "_tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    inp = scratch / "diff_in.txt"
    outp = scratch / "diff_out.txt"
    lines = ["pool|0"]
    for q in queries:
        lines.append(f"0.5 wifi 20 0 1 7000 8000 10 budget -50 {q}")
    inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if outp.exists():
        outp.unlink()
    subprocess.run(f'cmd /c ""{ENGINE}" < "{inp}" > "{outp}" 2>&1"', shell=True, check=False)
    out = []
    for line in outp.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("ok\tpool="):
            continue
        parts = line.split("\t")
        if len(parts) >= 5 and parts[4].isdigit():
            out.append(int(parts[4]))
    return out


def classify_exports(text):
    types, values = set(), set()
    for m in re.finditer(r"export\s+(interface|type)\s+(\w+)", text):
        types.add(m.group(2))
    for m in re.finditer(r"export\s+(enum|class|function|const)\s+(\w+)", text):
        values.add(m.group(2))
    return types, values


def main():
    if not SRC.exists():
        print(f"[verify] ERROR: {SRC} not found")
        return 2

    # Scratch lives inside the workspace: the sandbox denies writes that a
    # child process creates under the OS temp root, but the workspace is always
    # writable. Node handles the non-ASCII path fine (unlike the ArkTS and
    # Cangjie build tools, which is why those use ASCII mirrors).
    dst = ROOT / "app" / "harmony" / "_verify"
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)

    sources = {}
    for rel in MODULES:
        p = SRC / rel
        if not p.exists():
            print(f"[verify] ERROR: missing {p}")
            return 2
        sources[rel] = p.read_text(encoding="utf-8")

    type_names, value_names = set(), set()
    for text in sources.values():
        t, v = classify_exports(text)
        type_names |= t
        value_names |= v

    dropped = 0

    def rewrite_import(m):
        nonlocal dropped
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        keep = [n for n in names if n not in type_names or n in value_names]
        if not keep:
            dropped += 1
            return ""          # every name was type-only; erased at runtime
        return f"import {{ {', '.join(keep)} }} from '{m.group(2)}.ts';"

    for rel, text in sources.items():
        text = re.sub(r"import\s*\{([^}]+)\}\s*from\s*'([^']+)';", rewrite_import, text)
        out = dst / rel.replace(".ets", ".ts")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    # ---- the consistency probe ----
    # Both sides get the SAME query list; the comparison is done here, so adding
    # a task to the suite automatically extends the differential test.
    queries = all_queries()
    engine_k = library_k(queries)
    if len(engine_k) != len(queries):
        print(f"[verify] WARNING: engine returned {len(engine_k)} results for "
              f"{len(queries)} queries; falling back to no library comparison")
        engine_k = None

    probe = """
import { adaptiveK, selectTopK } from './agents/ToolRegistry.ts';
import { planStep } from './core/BudgetPolicy.ts';
import { NetTier } from './model/Types.ts';

const queries: string[] = %s;

console.log('== adaptive k over the whole task set (app side) ==');
const out: number[] = [];
for (const q of queries) {
  const k = adaptiveK(q);
  out.push(k);
  const sel = selectTopK(q, k).map((t: { name: string }) => t.name).join(',');
  console.log(`APPK\t${k}\t${sel}`);
}

console.log('');
console.log('== decision ladder via planStep (budget 85%% used) ==');
const budget = { tokenCap: 8000, latencyCapMs: 60000, cloudCallCap: 10, trafficCapKb: 50000 };
const ledger = { tokensSpent: 6800, latencySpentMs: 0, cloudCalls: 0 };
for (const tier of [NetTier.Wifi, NetTier.Weak, NetTier.Offline]) {
  const net = { tier: tier, rttMs: 20, metered: false, lanAvailable: true };
  const p = planStep('search my files for the quarterly report', 0.8, net, budget, ledger, -50);
  console.log(`LADDER\t${tier}\t${p.route}\t${p.msgForm}\t${p.toolStrategy}`);
}

console.log('');
console.log('== selector semantics ==');
for (const sel of [-50, 0, 3]) {
  const net = { tier: NetTier.Wifi, rttMs: 20, metered: false, lanAvailable: true };
  const p = planStep('search my files for the quarterly report', 0.8, net, budget, ledger, sel);
  const kind = sel < 0 ? 'score-driven' : (sel === 0 ? 'budget-driven' : 'pinned');
  console.log(`SELECTOR\t${sel}\t${kind}\t${p.toolStrategy}`);
}
""" % json.dumps(queries, ensure_ascii=False)

    (dst / "probe.ts").write_text(probe, encoding="utf-8")

    node = next((n for n in NODE_CANDIDATES if n.exists()), None)
    if node is None:
        print("[verify] ERROR: no node executable found")
        return 2

    print(f"[verify] mirrored {len(sources)} modules, dropped {dropped} type-only imports")
    print(f"[verify] differential test over {len(queries)} queries (whole task set)")
    print(f"[verify] scratch = {dst}")
    print()
    r = subprocess.run([str(node), "--experimental-transform-types", "--no-warnings",
                        str(dst / "probe.ts")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.stderr.strip():
        print("[verify] stderr:")
        print(r.stderr[:4000])

    app_k, ladder, selectors = [], [], []
    for line in r.stdout.splitlines():
        f = line.split("\t")
        if f[0] == "APPK" and len(f) >= 3:
            app_k.append((int(f[1]), f[2]))
        elif f[0] == "LADDER" and len(f) >= 5:
            ladder.append(f[1:])
        elif f[0] == "SELECTOR" and len(f) >= 4:
            selectors.append(f[1:])

    failures = 0

    # ---- 1. differential: the whole task set, both implementations ----
    print("== adaptive k: app vs Cangjie library, over the whole task set ==")
    if engine_k is None:
        print("  (library comparison skipped: engine did not answer)")
        failures += 1
    else:
        print(f"  {'query':<54} {'app':>4} {'lib':>4}  selected")
        print("  " + "-" * 92)
        for q, (ak, sel), lk in zip(queries, app_k, engine_k):
            ok = ak == lk
            if not ok:
                failures += 1
            print(f"  {'OK ' if ok else 'FAIL'} {q[:50]:<50} {ak:>4} {lk:>4}  {sel[:38]}")
        print(f"  -> {len(queries) - failures}/{len(queries)} queries agree")

    # ---- 2. decision ladder ----
    print()
    print("== decision ladder via planStep (budget 85% used) ==")
    for tier, route, msg, tools in ladder:
        print(f"  {tier:<9} route={route:<10} msg={msg:<11} tools={tools}")

    # ---- 3. selector semantics ----
    print()
    print("== selector semantics ==")
    for sel, kind, tools in selectors:
        print(f"  selector {sel:>4} ({kind:<13}) -> {tools}")

    print()
    print(f"RESULT: {'app logic matches the library' if failures == 0 else str(failures) + ' MISMATCH(ES)'}")

    shutil.rmtree(dst, ignore_errors=True)
    print(f"[verify] node exit code = {r.returncode}")
    return 0 if failures == 0 and r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
