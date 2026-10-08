#!/usr/bin/env python3
"""
OpenAI-compatible mock inference server (stdlib only).

WHY THIS EXISTS
    The full experiment pipeline -- task set, agent loop, the Cangjie decision
    engine, metric collection and reporting -- must be buildable and testable
    before any real model is available. This server stands in for the model so
    that pipeline bugs are found now rather than in week 14.

HONESTY NOTE -- READ BEFORE CITING ANY NUMBER
    Numbers produced against this mock are *pipeline validation*, not results.
    This server is a simulator of a small model, not a model. Paper numbers must
    come from a real endpoint (Ollama / llama.cpp on the edge node, or a cloud
    API). The harness is endpoint-agnostic precisely so the swap is one flag.

WHAT IT SIMULATES (and why each one matters)
    1. Tool choice. The model may only choose among tools whose FULL schema is
       present in the prompt. Tools offered as a one-line summary are visible by
       name but not by parameter detail. This is the causal mechanism behind the
       project's central tradeoff: compressing the tool context saves tokens but
       can cost correctness. It is not a synthetic "mode flag".
    2. Argument completeness. With a full schema the required arguments are
       filled; with a summary only, required arguments can be missed. Again this
       follows from the compression rather than from a laboratory switch.
    3. Latency. Prefill and decode times scale with prompt and completion length,
       so the tier/route decisions have measurable consequences.

USAGE
    python mock_llm_server.py --port 8100
    python mock_llm_server.py --port 8100 --seed 7 --summary-arg-omission-rate 0.35
"""

import argparse
import hashlib
import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "mock-small-model"


def estimate_tokens(s: str) -> int:
    """
    The project's single definition of "token".

    This must match `estimateTokens()` in the Cangjie library byte for byte.
    An earlier revision reported `len(prompt) // 4` here while the scheduler used
    the byte-weighted form below, so the recorded numbers and the decisions that
    produced them came from different estimators. On this project's ASCII
    workload the two coincide exactly, so no reported number changed -- but they
    diverge by up to 4.5x on pure CJK, which is precisely what a Chinese-language
    deployment would face. One definition, checked by the audit script.
    """
    raw = s.encode("utf-8")
    ascii_b = sum(1 for b in raw if b < 128)
    wide_b = len(raw) - ascii_b
    return max(1, ascii_b // 4 + (wide_b + 2) // 3)


class SimConfig:
    def __init__(self, args):
        self.seed = args.seed
        self.prefill_ms_per_token = args.prefill_ms_per_token
        self.decode_ms_per_token = args.decode_ms_per_token
        self.decode_tokens = args.decode_tokens
        self.omission_rate = args.summary_arg_omission_rate
        self.model = args.model


# --------------------------------------------------------------------------
# Prompt parsing
#
# The harness assembles the tool context in a fixed, inspectable format. The
# mock parses exactly that format -- it is coupled to the harness by design,
# and the contract is documented in experiments/README.md.
#
#   - <tool.name>: <one-line description> | params: a b c      <- summary form
#   FULL_SCHEMA: {"name": "...", "inputSchema": {...}}         <- full form
# --------------------------------------------------------------------------

SUMMARY_RE = re.compile(
    r"^\s*-\s*(?P<name>[A-Za-z0-9_.\-]+)\s*:\s*(?P<desc>[^|]*)\|\s*params:\s*(?P<params>.*)$",
    re.MULTILINE,
)
FULL_SCHEMA_RE = re.compile(r"^\s*FULL_SCHEMA:\s*(?P<json>\{.*\})\s*$", re.MULTILINE)


def parse_tool_context(prompt: str):
    """Return (summaries, full_schemas).

    summaries:    name -> {"desc": str, "params": [str]}
    full_schemas: name -> {"required": [str], "properties": [str]}
    """
    summaries = {}
    for m in SUMMARY_RE.finditer(prompt):
        name = m.group("name")
        params = [p for p in m.group("params").replace(",", " ").split() if p]
        summaries[name] = {"desc": m.group("desc").strip(), "params": params}

    full = {}
    for m in FULL_SCHEMA_RE.finditer(prompt):
        try:
            obj = json.loads(m.group("json"))
        except json.JSONDecodeError:
            continue
        name = obj.get("name")
        if not name:
            continue
        schema = obj.get("inputSchema", {}) or {}
        full[name] = {
            "required": list(schema.get("required", []) or []),
            "properties": list((schema.get("properties") or {}).keys()),
        }
    return summaries, full


STOPWORDS = {
    "the", "a", "an", "for", "my", "me", "to", "of", "in", "on", "with", "and",
    "from", "about", "at", "is", "it", "up", "look", "get", "please", "that",
    "this", "next", "last", "into", "out", "some", "any",
}


# A keyword simulator with no notion of synonyms routes "find online the release
# notes" to an arbitrary tool, because nothing in the utterance overlaps a tool
# name. A real model resolves that instantly, so a small synonym map is the
# minimum needed for the simulator to be a fair stand-in rather than a source of
# spurious failures. It is deliberately tiny and documented, not a hidden fudge.
SYNONYMS = {
    "online": "web", "internet": "web", "browse": "web",
    "notification": "notice", "alert": "notice", "notify": "notice", "push": "notice",
    "schedule": "calendar", "appointment": "calendar", "meeting": "calendar", "event": "calendar",
    "document": "file", "documents": "file", "docs": "file", "spreadsheet": "file",
    "slides": "file", "report": "file", "directory": "contact", "address": "contact",
    "phone": "contact", "number": "contact", "person": "contact",
}


def tokenize(text: str):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def expand(tokens):
    """Add canonical synonyms so the simulator can resolve non-literal phrasing."""
    return tokens | {SYNONYMS[t] for t in tokens if t in SYNONYMS}


def choose_tool(task: str, summaries: dict, full: dict):
    """Deterministic, keyword-based tool choice.

    Candidates are restricted to tools carrying a full schema, mirroring the
    fact that a model cannot reliably invoke what it can only see a summary of.
    Falls back to the summary pool when no schema is present at all.

    Weighting note: an earlier revision let generic description tokens such as
    "search" or "look up" outweigh the tool's own name, so "search my contact
    list" was routed to web.search. Name components now dominate and description
    overlap is stopword-filtered, which matches how a real model reads a tool
    catalogue far better than raw bag-of-words overlap does.
    """
    task_tokens = expand(tokenize(task))
    candidates = list(full.keys()) if full else list(summaries.keys())
    if not candidates:
        return None, "no tools offered"

    best, best_score = None, -1
    for name in candidates:
        parts = [p for p in re.split(r"[._\-]", name) if p]
        name_hits = sum(1 for p in parts if p in task_tokens)
        score = name_hits * 30
        if name_hits >= 2:
            score += 30  # two name components is a very strong signal
        desc = summaries.get(name, {}).get("desc", "")
        desc_tokens = expand(tokenize(desc)) - STOPWORDS
        score += len(desc_tokens & task_tokens) * 3
        if score > best_score:
            best, best_score = name, score
    return best, "keyword match"


def build_arguments(task: str, tool: str, summaries: dict, full: dict, rng: random.Random):
    """Produce tool arguments, modelling what the two renderings permit."""
    schema = full.get(tool)
    if schema:
        params = schema["required"] or schema["properties"]
        args = {p: f"<{p} from task>" for p in params}
        return args, "full-schema"

    # Summary form only: parameter detail is missing, so required arguments can
    # be omitted. Whether a given call is affected is deterministic per
    # (task, tool) so runs stay reproducible.
    info = summaries.get(tool, {})
    params = info.get("params", [])
    key = f"{task}|{tool}"
    h = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    if params and (h % 100) < int(rng.random() * 0 + 100 * OmissionRate.value):
        return {}, "summary-omitted-args"
    args = {p: f"<{p} from task>" for p in params}
    return args, "summary-partial"


class OmissionRate:
    value = 0.35


def decide(prompt: str, task: str, cfg: SimConfig):
    summaries, full = parse_tool_context(prompt)
    tool, why = choose_tool(task, summaries, full)
    if tool is None:
        return None, {}, "no-tool", why
    rng = random.Random(cfg.seed)
    args, arg_src = build_arguments(task, tool, summaries, full, rng)
    return tool, args, arg_src, why


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------


ROLE_RE = re.compile(r"^\s*ROLE:\s*(\w+)", re.MULTILINE)
REQ_RE = re.compile(r"^\s*REQUIRED_ARGS:\s*(.*)$", re.MULTILINE)


def role_of(prompt: str) -> str:
    m = ROLE_RE.search(prompt)
    return m.group(1) if m else "planner"


def required_args_of(prompt: str):
    m = REQ_RE.search(prompt)
    if not m:
        return []
    return [a.strip() for a in m.group(1).split(",") if a.strip()]


def respond(prompt: str, messages, cfg: SimConfig):
    """Return (message, finish_reason, sim_meta).

    Roles let one simulator stand in for a three-agent pipeline. The executor
    simply echoes what it was told to do; the verifier then has to *find* the
    arguments in the message it receives. That is what makes the message
    representation decision observable: a truncating summary destroys exactly
    the fields the verifier needs to confirm.
    """
    role = role_of(prompt)
    task = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            task = str(m.get("content", ""))
            break

    if role == "executor":
        # A tool execution: deterministic, and it echoes the received
        # instruction verbatim so any information loss upstream is visible.
        return ({"role": "assistant", "content": "EXECUTED: " + task, "tool_calls": []},
                "stop", {"role": role})

    if role == "verifier":
        required = required_args_of(prompt)
        missing = [a for a in required if a not in task]
        verdict = "OK" if not missing else "FAIL"
        return ({"role": "assistant",
                 "content": f"VERDICT: {verdict}" + (f" missing={','.join(missing)}" if missing else ""),
                 "tool_calls": []},
                "stop", {"role": role, "missing": missing})

    # Default: the planner chooses a tool.
    tool, args, arg_src, why = decide(prompt, task, cfg)
    if tool is None:
        return ({"role": "assistant", "content": "I cannot complete this task.", "tool_calls": []},
                "stop", {"role": role, "arg_source": arg_src})
    return ({"role": "assistant", "content": None,
             "tool_calls": [{
                 "id": "call_" + hashlib.sha1(f"{task}{tool}".encode()).hexdigest()[:12],
                 "type": "function",
                 "function": {"name": tool, "arguments": json.dumps(args)},
             }]},
            "tool_calls",
            {"role": role, "arg_source": arg_src, "choice_reason": why,
             "tools_full": len(parse_tool_context(prompt)[1])})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    cfg = None

    def log_message(self, fmt, *args):  # keep the harness output readable
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._send(200, {"object": "list", "data": [{"id": self.cfg.model, "object": "model"}]})
        elif self.path.startswith("/health"):
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self._send(404, {"error": {"message": "not found"}})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._send(400, {"error": {"message": f"bad json: {exc}"}})
            return

        messages = req.get("messages", [])
        prompt = "\n".join(str(m.get("content", "")) for m in messages)

        message, finish, sim = respond(prompt, messages, self.cfg)

        # Simulated latency: prefill scales with prompt, decode is fixed.
        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = self.cfg.decode_tokens
        time.sleep(
            (prompt_tokens * self.cfg.prefill_ms_per_token
             + completion_tokens * self.cfg.decode_ms_per_token) / 1000.0
        )

        self._send(200, {
            "id": "chatcmpl-" + hashlib.sha1(prompt.encode()).hexdigest()[:16],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.cfg.model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            # Non-standard, but invaluable for auditing why a run behaved as it did.
            "x_sim": sim,
        })


def main():
    ap = argparse.ArgumentParser(description="OpenAI-compatible mock inference server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--prefill-ms-per-token", type=float, default=0.35)
    ap.add_argument("--decode-ms-per-token", type=float, default=12.0)
    ap.add_argument("--decode-tokens", type=int, default=24)
    ap.add_argument("--summary-arg-omission-rate", type=float, default=0.35)
    args = ap.parse_args()

    OmissionRate.value = args.summary_arg_omission_rate
    Handler.cfg = SimConfig(args)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[mock-llm] listening on http://{args.host}:{args.port}/v1  model={args.model}", flush=True)
    print(f"[mock-llm] seed={args.seed} prefill={args.prefill_ms_per_token}ms/tok "
          f"decode={args.decode_ms_per_token}ms/tok omission_rate={args.summary_arg_omission_rate}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
