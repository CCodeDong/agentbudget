#!/usr/bin/env python3
"""
Experiment harness for the on-device multi-agent context-budget scheduler.

WHAT THIS MEASURES
    For each task, under a given network profile, the harness asks the Cangjie
    decision engine (``projects/agentbudget4cj``) where a step should execute and
    how the tool context should be rendered, assembles the prompt accordingly,
    calls the model, and verifies the resulting tool call.

    It then reports, per (mode, network profile):
      * task success rate
      * prompt tokens consumed
      * measured end-to-end latency
      * cloud calls consumed and route distribution

WHAT THIS DOES **NOT** MEASURE
    The default endpoint is the mock simulator (``mock_llm_server.py``), because
    the pipeline must be provably correct before a real model is wired in.
    Numbers produced against the mock are *pipeline validation*:
      * success rate and prompt tokens are meaningful as a demonstration that the
        harness exercises the intended tradeoff;
      * latency is SIMULATED by the mock and must never be reported as a result.
    For paper numbers, point ``--edge-url`` / ``--cloud-url`` at a real endpoint
    (Ollama or llama.cpp on the edge node, a cloud API for the cloud tier).

DESIGN CONSTRAINT
    Subprocess pipes are unavailable in this sandbox, so the engine is driven
    through FILE REDIRECTION. See docs/05-实验管线接口.md.

USAGE
    python experiment.py --out results
    python experiment.py --out results --edge-url http://127.0.0.1:11434/v1 --cloud-url https://api.example/v1
"""

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
DEFAULT_ENGINE = WORKSPACE / "projects" / "agentbudget4cj" / "bin" / "agentbudget4cj.exe"


# ---------------------------------------------------------------------------
# Tool pool -- MUST mirror `defaultPool()` in projects/agentbudget4cj/src/main.cj
# ---------------------------------------------------------------------------

def _schema(name, desc, params):
    props = {p: {"type": "string", "description": f"the {p} argument"} for p in params}
    return {
        "name": name,
        "description": (
            f"{desc} -- a verbose description mirroring what an MCP server really ships, "
            "including usage notes that inflate the injected context"
        ),
        "inputSchema": {"type": "object", "properties": props, "required": list(params)},
    }


TOOLS = [
    {"name": "calendar.create", "desc": "create a calendar event", "params": ["title", "start"],
     "schema": _schema("calendar.create", "create a calendar event", ["title", "start"])},
    {"name": "contact.lookup", "desc": "look up a contact by name", "params": ["name"],
     "schema": _schema("contact.lookup", "look up a contact by name", ["name"])},
    {"name": "file.search", "desc": "search files by keyword", "params": ["query", "limit"],
     "schema": _schema("file.search", "search files by keyword", ["query", "limit"])},
    {"name": "notice.send", "desc": "send a notification", "params": ["text"],
     "schema": _schema("notice.send", "send a notification", ["text"])},
    {"name": "web.search", "desc": "search the web", "params": ["query", "limit"],
     "schema": _schema("web.search", "search the web", ["query", "limit"])},
    # Distractors -- must mirror defaultPool() in src/main.cj. A five-tool pool
    # makes top-k retrieval trivially correct and hides the cost side of
    # compression, so the pool is deliberately enlarged here.
    {"name": "sms.send", "desc": "send a text message", "params": ["to", "body"],
     "schema": _schema("sms.send", "send a text message", ["to", "body"])},
    {"name": "email.compose", "desc": "compose an email", "params": ["to", "subject", "body"],
     "schema": _schema("email.compose", "compose an email", ["to", "subject", "body"])},
    {"name": "music.play", "desc": "play music by name", "params": ["track"],
     "schema": _schema("music.play", "play music by name", ["track"])},
    {"name": "map.navigate", "desc": "navigate to a destination", "params": ["place"],
     "schema": _schema("map.navigate", "navigate to a destination", ["place"])},
    {"name": "timer.set", "desc": "set a countdown timer", "params": ["minutes"],
     "schema": _schema("timer.set", "set a countdown timer", ["minutes"])},
    {"name": "alarm.create", "desc": "create an alarm", "params": ["time"],
     "schema": _schema("alarm.create", "create an alarm", ["time"])},
    {"name": "weather.query", "desc": "query the weather forecast", "params": ["city"],
     "schema": _schema("weather.query", "query the weather forecast", ["city"])},
    {"name": "translate.text", "desc": "translate text", "params": ["text", "target"],
     "schema": _schema("translate.text", "translate text", ["text", "target"])},
    {"name": "clipboard.read", "desc": "read the clipboard", "params": [],
     "schema": _schema("clipboard.read", "read the clipboard", [])},
    {"name": "battery.status", "desc": "report battery status", "params": [],
     "schema": _schema("battery.status", "report battery status", [])},
]


# ---------------------------------------------------------------------------
# Task set
#
# Deliberately small but varied, and every utterance carries the lexical signal
# that the naive selector keys on. That is the point: with a lexical selector,
# retrieval failures are a property of the task wording, which is exactly the
# phenomenon the budget scheduler has to survive.
# ---------------------------------------------------------------------------

def _tasks():
    out = []
    specs = [
        ("calendar.create", ["title", "start"], "hard", [
            "create a calendar event for the design review tomorrow at three",
            "add a calendar event titled standup every weekday morning",
            "put a calendar event on my schedule for the client call",
            "schedule a calendar event for the project kickoff on friday",
            "make a calendar event for the dentist appointment next tuesday",
            "create a calendar event to remind me about the conference talk",
        ]),
        ("contact.lookup", ["name"], "easy", [
            "look up a contact named Li Wei in my address book",
            "find the contact record for my supervisor Zhang",
            "find the contact card for the person from the vendor",
            "search my contact list for the person from the vendor",
            "look up a contact so I can email the teaching assistant",
            "identify the contact name from yesterday's meeting invite",
        ]),
        ("file.search", ["query", "limit"], "medium", [
            "search files for the quarterly report draft",
            "find files containing the budget spreadsheet",
            "search my files for the lecture slides from last week",
            "locate files by keyword about the literature review",
            "search files for anything mentioning the experiment log",
            "find the file with the project proposal revision",
        ]),
        ("notice.send", ["text"], "easy", [
            "send a notification to remind me about the deadline",
            "post a notification that the build finished",
            "send a notification with the meeting link",
            "push a notification about the low battery warning",
            "send a notification telling me to submit the assignment",
            "post a notification when the download completes",
        ]),
        ("web.search", ["query", "limit"], "medium", [
            "search the web for the latest news on agent frameworks",
            "search online for tomorrow's weather forecast",
            "search the web for the documentation of that API",
            "find online the release notes for the new version",
            "search the web for recent papers about on-device inference",
            "search online for the train schedule to the conference",
        ]),
    ]
    for gold, req, diff, utterances in specs:
        for i, u in enumerate(utterances):
            out.append({
                "id": f"{gold}#{i}",
                "utterance": u,
                "gold_tool": gold,
                "required_args": req,
                "difficulty": {"easy": 0.2, "medium": 0.5, "hard": 0.8}[diff],
            })
    return out


TASKS = _tasks()


# ---------------------------------------------------------------------------
# Network profiles
# ---------------------------------------------------------------------------

NET_PROFILES = {
    # name: (tier, rtt_ms, metered, lan)
    "wifi":        ("wifi", 20, False, True),
    "wifi_nolan":  ("wifi", 20, False, False),
    "weak_lan":    ("weak", 1500, True, True),
    "weak_nolan":  ("weak", 1500, True, False),
    "offline":     ("offline", 0, False, False),
}


# ---------------------------------------------------------------------------
# Bridge to the Cangjie decision engine
# ---------------------------------------------------------------------------

class DecisionEngine:
    def __init__(self, exe: Path, pool_limit: int = 0):
        self.exe = Path(exe)
        self.pool_limit = pool_limit
        if not self.exe.exists():
            raise FileNotFoundError(
                f"decision engine not found: {self.exe}\n"
                f"build it first:  powershell -ExecutionPolicy Bypass -File tools\\cj.ps1 "
                f"-Project agentbudget4cj bin"
            )

    def plan_batch(self, requests):
        """Drive the CLI over file redirection (pipes are unavailable).

        The scratch files live inside the session workspace rather than the
        system temp directory: the sandbox denies writes that a child process
        creates under the OS temp root, but the workspace is always writable.

        Each batch is a FRESH process, so the pool limit has to be re-sent as the
        first line of every batch -- the `pool` verb is stateful but the process
        is not persistent. Its acknowledgement line is filtered back out.
        """
        lines = []
        if self.pool_limit > 0:
            lines.append(f"pool|{self.pool_limit}")
        for r in requests:
            lines.append(
                f'{r["difficulty"]} {r["tier"]} {r["rtt_ms"]} {int(r["metered"])} '
                f'{int(r["lan"])} {r["tokens_spent"]} {r["token_cap"]} '
                f'{r["cloud_calls_left"]} {r["mode"]} {r["top_k"]} {r["query"]}'
            )
        scratch = HERE / "_tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        inp = scratch / "engine_in.txt"
        outp = scratch / "engine_out.txt"
        inp.write_text("\n".join(lines) + "\n", encoding="utf-8")  # no BOM
        if outp.exists():
            outp.unlink()
        cmd = f'cmd /c ""{self.exe}" < "{inp}" > "{outp}" 2>&1"'
        subprocess.run(cmd, shell=True, check=False)
        raw = outp.read_text(encoding="utf-8", errors="replace").splitlines()
        if self.pool_limit > 0:
            raw = [ln for ln in raw if not ln.startswith("ok\tpool=")]

        out = []
        for line in raw:
            parts = line.split("\t")
            if len(parts) < 7:
                out.append({"error": line})
                continue
            out.append({
                "route": parts[0], "msg_form": parts[1], "tool_strategy": parts[2],
                "tool_tokens": int(parts[3]) if parts[3].isdigit() else -1,
                # k_used == 0 means every tool's full schema was injected.
                "k_used": int(parts[4]) if parts[4].isdigit() else -1,
                "selected": [s for s in parts[5].split(",") if s],
                "reason": parts[6],
            })
        if len(out) != len(requests):
            raise RuntimeError(f"engine returned {len(out)} lines for {len(requests)} requests")
        return out

    def codec_batch(self, pairs):
        """Render inter-agent messages.

        pairs: (form, budget, from, to, intent, payload) where `budget` is the
        character budget of the truncating `summary` form. It is a parameter so
        the effect of truncation strength can be swept; the report's claim that
        the truncating form is dominated must hold across budgets, not at one
        hand-picked value.

        Returns [(rendered, token_cost)]. The rendering stays inside the Cangjie
        artifact on purpose -- if Python rendered these, the experiment would be
        measuring Python's codec rather than the library under study.
        """
        lines = [f"codec|{form}|{budget}|{frm}|{to}|{intent}|{payload}"
                 for form, budget, frm, to, intent, payload in pairs]
        scratch = HERE / "_tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        inp = scratch / "codec_in.txt"
        outp = scratch / "codec_out.txt"
        inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if outp.exists():
            outp.unlink()
        cmd = f'cmd /c ""{self.exe}" < "{inp}" > "{outp}" 2>&1"'
        subprocess.run(cmd, shell=True, check=False)
        raw = outp.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for line in raw:
            parts = line.split("\t")
            if len(parts) < 2:
                out.append(("", 0))
                continue
            out.append((parts[0], int(parts[1]) if parts[1].isdigit() else 0))
        if len(out) != len(pairs):
            raise RuntimeError(f"codec returned {len(out)} lines for {len(pairs)} messages")
        return out


# ---------------------------------------------------------------------------
# Prompt assembly -- the contract the mock parser expects
# ---------------------------------------------------------------------------

def set_pool_limit(n):
    """Mirror --pool on the harness side.

    The engine's pool decides which tools can be SELECTED, but the prompt the
    model sees is assembled here from TOOLS. Limiting only one side would make
    them disagree: the recorded prompt_tokens would describe a different tool
    set than the one the engine chose from, and every comparison would be
    measuring an inconsistency rather than a policy.
    """
    global TOOLS
    if n > 0:
        TOOLS = TOOLS[:n]


def build_system_prompt(selected, mode):
    lines = ["You are a multi-agent mobile assistant. Available tools:"]
    for t in TOOLS:
        lines.append(f"- {t['name']}: {t['desc']} | params: {' '.join(t['params'])}")
    lines.append("")
    lines.append("Full schemas:")
    for t in TOOLS:
        # In budget mode only the selected tools expose a full schema; the rest
        # remain visible by summary alone. That asymmetry is the whole point.
        if mode == "eager" or t["name"] in selected:
            lines.append("FULL_SCHEMA: " + json.dumps(t["schema"], ensure_ascii=False))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def call_model(base_url, model, messages, timeout=120):
    payload = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify(response, task):
    choices = response.get("choices") or []
    if not choices:
        return False, "no choices"
    msg = choices[0].get("message") or {}
    calls = msg.get("tool_calls") or []
    if not calls:
        return False, "no tool call"
    fn = calls[0].get("function") or {}
    name = fn.get("name")
    if name != task["gold_tool"]:
        return False, f"wrong tool: {name}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        return False, "arguments not valid json"
    missing = [a for a in task["required_args"] if a not in args]
    if missing:
        return False, "missing args: " + ",".join(missing)
    return True, "ok"


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def run_once(task, mode, engine, dec, urls, model, net, budget):
    messages = [
        {"role": "system", "content": build_system_prompt(dec["selected"], mode)},
        {"role": "user", "content": task["utterance"]},
    ]
    url = urls["cloud"] if dec["route"] == "cloud" else urls["edge"]

    t0 = time.perf_counter()
    error = ""
    try:
        response = call_model(url, model, messages)
    except Exception as exc:  # noqa: BLE001 - surfaced into the record
        response = {}
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = (time.perf_counter() - t0) * 1000.0

    ok, detail = (False, "request failed") if error else verify(response, task)
    usage = response.get("usage") or {}
    sim = response.get("x_sim") or {}

    return {
        "task_id": task["id"],
        "gold_tool": task["gold_tool"],
        "mode": mode,
        "net": net["name"],
        "route": dec["route"],
        "msg_form": dec["msg_form"],
        "tool_strategy": dec["tool_strategy"],
        "engine_tool_tokens": dec["tool_tokens"],
        "selected_tools": "|".join(dec["selected"]),
        "gold_in_selected": task["gold_tool"] in dec["selected"],
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "latency_ms": round(latency_ms, 2),
        "cloud_calls": 1 if dec["route"] == "cloud" else 0,
        "success": ok,
        "detail": detail,
        "arg_source": sim.get("arg_source", ""),
        "engine_reason": dec["reason"],
        "error": error,
    }


# ---------------------------------------------------------------------------
# Multi-turn agent loop (planner -> executor -> verifier)
#
# This is what makes the message-representation decision observable. The single
# step loop only ever measures tool-context compression; here the scheduler's
# chosen `msgForm` is applied to the *inter-agent* messages, and the verifier has
# to find the tool arguments inside the message it receives. A representation
# that loses those arguments therefore shows up as a verification failure rather
# than as an invisible cost.
# ---------------------------------------------------------------------------

def run_multiturn(task, mode, engine, dec, urls, model, net, summary_budget=40):
    planner_sys = build_system_prompt(dec["selected"], mode) + "\nROLE: planner"
    url = urls["cloud"] if dec["route"] == "cloud" else urls["edge"]
    form = dec["msg_form"]

    tok = 0
    lat = 0.0
    t0 = time.perf_counter()
    try:
        r1 = call_model(url, model, [{"role": "system", "content": planner_sys},
                                     {"role": "user", "content": task["utterance"]}])
    except Exception as exc:
        return {"task_id": task["id"], "mode": mode, "net": net["name"], "msg_form": form,
                "summary_budget": summary_budget,
                "success": False, "detail": f"planner call failed: {exc}", "prompt_tokens": 0}
    lat += (time.perf_counter() - t0) * 1000
    tok += (r1.get("usage") or {}).get("prompt_tokens", 0)

    calls = (r1.get("choices") or [{}])[0].get("message", {}).get("tool_calls") or []
    tool = calls[0]["function"]["name"] if calls else ""
    args_json = (calls[0]["function"].get("arguments") if calls else "") or "{}"

    msg1, c1 = engine.codec_batch(
        [(form, summary_budget, "planner", "executor", "instruction", args_json)])[0]

    t0 = time.perf_counter()
    r2 = call_model(urls["edge"], model, [{"role": "system", "content": "ROLE: executor"},
                                          {"role": "user", "content": msg1}])
    lat += (time.perf_counter() - t0) * 1000
    tok += (r2.get("usage") or {}).get("prompt_tokens", 0)
    exec_out = (r2.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    msg2, c2 = engine.codec_batch(
        [(form, summary_budget, "executor", "verifier", "result", exec_out)])[0]

    verifier_sys = "ROLE: verifier\nREQUIRED_ARGS: " + ", ".join(task["required_args"])
    t0 = time.perf_counter()
    r3 = call_model(urls["edge"], model, [{"role": "system", "content": verifier_sys},
                                          {"role": "user", "content": msg2}])
    lat += (time.perf_counter() - t0) * 1000
    tok += (r3.get("usage") or {}).get("prompt_tokens", 0)
    verdict = (r3.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    tool_ok = tool == task["gold_tool"]
    verified = "VERDICT: OK" in verdict
    return {
        "task_id": task["id"], "gold_tool": task["gold_tool"], "mode": mode,
        "net": net["name"], "route": dec["route"], "msg_form": form,
        "summary_budget": summary_budget,
        "tool_strategy": dec["tool_strategy"], "selected_tools": "|".join(dec["selected"]),
        "gold_in_selected": task["gold_tool"] in dec["selected"],
        "tool_correct": tool_ok, "codec_tokens": c1 + c2, "prompt_tokens": tok,
        "latency_ms": round(lat, 2), "cloud_calls": 1 if dec["route"] == "cloud" else 0,
        "success": bool(tool_ok and verified), "detail": verdict.strip()[:100],
        "engine_reason": dec["reason"], "error": "",
    }


# ---------------------------------------------------------------------------
# Experiment driver
# ---------------------------------------------------------------------------

def _normalize_argv(argv):
    """Let `--ks -50,0,1,3,5,8` parse without an equals sign.

    Negative selectors are meaningful here (they encode a threshold percentage),
    but argparse treats a token like `-50,0,...` as an option rather than a
    value, so `--ks -50,0,1,3,5,8` fails with "expected one argument". Silently
    requiring `--ks=` is a trap: the commands quoted in the docs would not run
    when copied. Merging the two tokens makes both spellings work.
    """
    out, i = [], 0
    negative_value_flags = ("--ks", "--utils", "--summary-budgets")
    while i < len(argv):
        tok = argv[i]
        follows = (i + 1 < len(argv)) and re.match(r"^-\d", argv[i + 1])
        if (tok in negative_value_flags) and follows:
            out.append(tok + "=" + argv[i + 1])
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser(description="context-budget scheduler experiment harness")
    ap.add_argument("--engine", default=str(DEFAULT_ENGINE))
    ap.add_argument("--edge-url", default="http://127.0.0.1:8100/v1")
    ap.add_argument("--cloud-url", default="http://127.0.0.1:8100/v1")
    ap.add_argument("--model", default="mock-small-model")
    ap.add_argument("--token-cap", type=int, default=8000)
    ap.add_argument("--cloud-cap", type=int, default=10)
    ap.add_argument("--modes", default="eager,budget")
    ap.add_argument("--nets", default="wifi,weak_lan,weak_nolan")
    # Budget pressure is a first-class experimental variable, not a constant.
    # The scheduler keeps the eager (all-schemas) context while headroom looks
    # ample, so a single mid-episode point would never exercise two-stage
    # injection and the two arms would measure identically.
    ap.add_argument("--utils", default="0.25,0.55,0.85",
                    help="fraction of the token budget already spent")
    # top-k is the direct knob between how much context is compressed and how
    # likely the correct tool survives retrieval, so it is a swept variable.
    # k=0 selects the scheduler's ADAPTIVE policy, which derives k from the
    # remaining budget -- the point being to test whether a joint policy beats
    # the best fixed value.
    # Negative values select the score-driven adaptive policy and encode the
    # threshold as a percentage of the top score (-50 is the paper's method);
    # 0 selects the budget-driven policy, which is a reported baseline; positive
    # values pin k to reproduce the fixed-k baselines.
    ap.add_argument("--ks", default="3",
                    help="top-k selectors: <0 score-driven (|k|=alpha%%), "
                         "0 budget-driven baseline, >0 fixed k")
    # The pool is compiled into the Cangjie engine; the harness mirrors it in
    # TOOLS. --pool limits both so the early five-tool experiment (whose data
    # the paper reports) stays reproducible after the pool grew to fifteen.
    ap.add_argument("--pool", type=int, default=0,
                    help="restrict the tool pool to its first N tools (0 = all)")
    ap.add_argument("--limit", type=int, default=0, help="cap tasks per profile (0 = all)")
    ap.add_argument("--multiturn", action="store_true",
                    help="run the planner->executor->verifier loop so the message "
                         "representation decision becomes observable")
    # The character budget of the truncating `summary` form. Sweeping it turns
    # "summary is dominated" from a single observation into a regularity: the
    # claim is only interesting if it holds at every budget, not at one value.
    ap.add_argument("--summary-budgets", default="40",
                    help="comma-separated character budgets for the summary form")
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args(_normalize_argv(sys.argv[1:]))

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    engine = DecisionEngine(Path(args.engine), args.pool)
    set_pool_limit(args.pool)
    urls = {"edge": args.edge_url, "cloud": args.cloud_url}
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    nets = [NET_PROFILES[n.strip()] for n in args.nets.split(",") if n.strip()]
    utils = [float(u) for u in args.utils.split(",") if u.strip()]
    ks = [int(k) for k in args.ks.split(",") if k.strip()]
    budgets = [int(b) for b in args.summary_budgets.split(",") if b.strip()]
    tasks = TASKS[: args.limit] if args.limit else TASKS

    records = []
    for mode in modes:
        for tier, rtt, metered, lan in nets:
            net = {"name": f"{tier}{'_lan' if lan else '_nolan'}", "tier": tier,
                   "rtt": rtt, "metered": metered, "lan": lan}
            for util in utils:
                budget = {"spent": int(args.token_cap * util), "cap": args.token_cap,
                          "cloud_left": args.cloud_cap}
                for top_k in ks:
                    for sb in budgets:
                        requests = [{
                            "difficulty": t["difficulty"], "tier": net["tier"], "rtt_ms": net["rtt"],
                            "metered": net["metered"], "lan": net["lan"],
                            "tokens_spent": budget["spent"], "token_cap": budget["cap"],
                            "cloud_calls_left": budget["cloud_left"], "mode": mode,
                            "top_k": top_k, "query": t["utterance"],
                        } for t in tasks]

                        decisions = engine.plan_batch(requests)
                        for task, dec in zip(tasks, decisions):
                            if "error" in dec:
                                records.append({"task_id": task["id"], "mode": mode, "net": net["name"],
                                                "budget_util": util, "top_k": top_k,
                                                "summary_budget": sb,
                                                "error": dec["error"], "success": False})
                                continue
                            if args.multiturn:
                                rec = run_multiturn(task, mode, engine, dec, urls, args.model, net, sb)
                            else:
                                rec = run_once(task, mode, engine, dec, urls, args.model, net, budget)
                            rec["budget_util"] = util
                            rec["top_k"] = top_k
                            rec["summary_budget"] = sb
                            records.append(rec)
                        print(f"[harness] {mode:>6} / {net['name']:<11} / util={util:<4} / "
                              f"k={top_k:<2} / sumBudget={sb:<4} {len(tasks):>3} runs", flush=True)

    # ---- persist raw records ----
    csv_path = outdir / "runs.csv"
    fields = sorted({k for r in records for k in r})
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(r)

    # ---- aggregate ----
    summary = {}
    for r in records:
        key = (r.get("mode"), r.get("net"), r.get("budget_util"), r.get("top_k"),
               r.get("summary_budget"))
        summary.setdefault(key, []).append(r)

    rows = []
    for (mode, net, util, k, sb), rs in sorted(
            summary.items(),
            key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0, kv[0][3] or 0, kv[0][4] or 0)):
        n = len(rs)
        succ = sum(1 for r in rs if r.get("success"))
        ptoks = [r.get("prompt_tokens", 0) for r in rs]
        lat = [r.get("latency_ms", 0.0) for r in rs]
        routes = {}
        for r in rs:
            routes[r.get("route")] = routes.get(r.get("route"), 0) + 1
        strategies = {}
        for r in rs:
            strategies[r.get("tool_strategy")] = strategies.get(r.get("tool_strategy"), 0) + 1
        forms = {}
        for r in rs:
            forms[r.get("msg_form")] = forms.get(r.get("msg_form"), 0) + 1
        rows.append({
            "mode": mode, "net": net, "budget_util": util, "top_k": k,
            "summary_budget": sb, "runs": n,
            "success_rate": round(succ / n, 4) if n else 0.0,
            "mean_prompt_tokens": round(statistics.mean(ptoks), 1) if ptoks else 0.0,
            "mean_latency_ms": round(statistics.mean(lat), 2) if lat else 0.0,
            "cloud_calls": sum(r.get("cloud_calls", 0) for r in rs),
            "gold_retrieved_rate": round(
                sum(1 for r in rs if r.get("gold_in_selected")) / n, 4) if n else 0.0,
            "routes": json.dumps(routes, ensure_ascii=False),
            "strategies": json.dumps(strategies, ensure_ascii=False),
            "forms": json.dumps(forms, ensure_ascii=False),
        })

    sum_path = outdir / "summary.csv"
    with sum_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["mode"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    json_path = outdir / "summary.json"
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- print ----
    print()
    hdr = (f"{'mode':<7} {'net':<12} {'util':>5} {'k':>3} {'sb':>4} {'runs':>5} {'succ':>7} {'prompt_tok':>11} "
           f"{'lat_ms':>9} {'cloud':>6} {'gold_ret':>9}  routes / strategies / forms")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['mode']:<7} {r['net']:<12} {r['budget_util']:>5} {r['top_k']:>3} "
              f"{r['summary_budget']:>4} {r['runs']:>5} "
              f"{r['success_rate']:>7.3f} {r['mean_prompt_tokens']:>11.1f} "
              f"{r['mean_latency_ms']:>9.2f} {r['cloud_calls']:>6} "
              f"{r['gold_retrieved_rate']:>9.3f}  {r['routes']} {r['strategies']} {r['forms']}")

    print(f"\n[harness] raw     -> {csv_path}")
    print(f"[harness] summary -> {sum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
