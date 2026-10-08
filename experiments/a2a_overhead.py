#!/usr/bin/env python3
"""
A2A envelope overhead analysis (device-independent).

WHY THIS EXISTS
    The HarmonyOS A2A protocol is the transport for the mobile orchestration
    layer, but no academic work has characterised its cost. Real device numbers
    need a phone; the *structural* overhead, however, follows directly from the
    type declarations and can be computed now.

    The wire format is JSON: `Server.onMessage(data: string, sender)` takes a
    string, and `Server.updateStatus(taskId, status)` / `addArtifact(taskId, p)`
    carry `TaskStatus` / `TaskArtifactParam` objects. So the cost of one A2A
    message is the JSON encoding of a `Message` (optionally embedded in a `Task`
    with `history`).

TYPES (verbatim from sdk/default/hms/ets/api/@hms.ai.A2A.d.ts, since 26.0.0)
    Message     { messageId, role, parts, contextId?, extensions?, metadata?,
                  referenceTaskIds?, taskId? }
    Part        { text?, raw?, url?, data?, mediaType?, filename?, metadata? }
    TaskStatus  { state, timestamp?, message? }
    Task        { id, contextId, status, artifacts?, history?, metadata? }
    Artifact    { artifactId, parts, description?, extensions?, metadata?, name? }

WHAT THIS MEASURES
    1. The fixed envelope cost per message, and what fraction of a real message
       it represents.
    2. Whether the envelope changes the ranking of message representations
       (natural vs truncating summary vs structured) established in the
       single-process codec.
    3. How `Task.history` accumulation scales -- i.e. the cost of carrying
       conversation state, which is the A2A analogue of context growth.

LIMITATION -- STATE THIS WHEN CITING
    This is a *schema-level* estimate computed from the type declarations, in the
    same JSON encoding ArkTS would produce. It excludes any transport framing the
    HSP proxy may add, and it is not a measurement of a running device. Treat it
    as an upper-bound-by-construction on payload efficiency, not as a device
    measurement.
"""

import json

# ---------------------------------------------------------------------------
# Token estimator identical in spirit to estimateTokens() in the Cangjie library:
# ASCII ~4 chars/token, non-ASCII ~1 token per character.
# ---------------------------------------------------------------------------

def estimate_tokens(s: str) -> int:
    ascii_n = sum(1 for ch in s if ord(ch) < 128)
    wide = len(s) - ascii_n
    return ascii_n // 4 + (wide + 2) // 3


def message(message_id, role, parts):
    return {"messageId": message_id, "role": role, "parts": parts}


def minimal_part(text):
    """The leanest Part the schema allows for textual content."""
    return {"text": text}


def structured_part(data):
    """A Part carrying structured data rather than prose."""
    return {"data": data, "mediaType": "application/json"}


def task(task_id, context_id, state, history=None, artifacts=None):
    t = {"id": task_id, "contextId": context_id,
         "status": {"state": state, "timestamp": "2026-09-23T21:00:00.000Z"}}
    if history:
        t["history"] = history
    if artifacts:
        t["artifacts"] = artifacts
    return t


# A representative tool invocation produced by the planner.
ARGS = {"query": "quarterly report", "limit": "5"}
# Compact, because that is what ArkTS JSON.stringify produces. Using the default
# (spaced) separators here would have confounded the text-vs-data comparison in
# section [5] by inflating the string form.
ARGS_JSON = json.dumps(ARGS, separators=(",", ":"))

# The three payload representations from the Cangjie codec, for comparison.
PAYLOADS = {
    # what the codec renders for MsgForm.Natural
    "natural": (f"Agent planner is sending the following instruction to agent "
                f"executor: {ARGS_JSON}"),
    # MsgForm.Summary with the codec's 40-character budget
    "summary": f"[planner->executor] instruction: {ARGS_JSON[:40]}",
    # MsgForm.Structured
    "structured": f"planner|executor|instruction|{ARGS_JSON}",
}


def enc(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def main():
    print("=" * 78)
    print("A2A ENVELOPE OVERHEAD  (schema-level estimate, NOT a device measurement)")
    print("=" * 78)

    # ---- 1. envelope cost of one bare Message -----------------------------
    empty_msg = message("msg-00000000-0000-0000-0000-000000000000", 0, [minimal_part("")])
    envelope_bytes = len(enc(empty_msg))
    print("\n[1] Fixed envelope per Message (empty payload)")
    print(f"    required fields only : {enc(empty_msg)}")
    print(f"    bytes                : {envelope_bytes}")
    print(f"    est. tokens          : {estimate_tokens(enc(empty_msg))}")

    # ---- 2. envelope as a share of a realistic message --------------------
    print("\n[2] Envelope share for the three payload representations")
    print(f"    {'form':<11} {'payload B':>10} {'total B':>9} {'envelope %':>11} {'est. tok':>9}")
    print("    " + "-" * 54)
    for name, payload in PAYLOADS.items():
        p = minimal_part(payload)
        msg = message("msg-00000000-0000-0000-0000-000000000000", 0, [p])
        total = len(enc(msg))
        share = 100.0 * (total - len(payload)) / total
        print(f"    {name:<11} {len(payload):>10} {total:>9} {share:>10.1f}% "
              f"{estimate_tokens(enc(msg)):>9}")

    # ---- 3. does the envelope change the ranking? -------------------------
    print("\n[3] Ranking check: does the A2A envelope reorder the representations?")
    rows = []
    for name, payload in PAYLOADS.items():
        msg = message("msg-00000000-0000-0000-0000-000000000000", 0, [minimal_part(payload)])
        rows.append((name, len(payload), len(enc(msg))))
    by_payload = [r[0] for r in sorted(rows, key=lambda r: r[1])]
    by_total = [r[0] for r in sorted(rows, key=lambda r: r[2])]
    print(f"    cheapest by payload alone : {by_payload}")
    print(f"    cheapest including envelope: {by_total}")
    print(f"    ranking preserved          : {by_payload == by_total}")

    # ---- 4. Task.history accumulation -------------------------------------
    print("\n[4] Task envelope cost as history accumulates (Task.history: Message[])")
    history = []
    print(f"    {'history':>8} {'bytes':>9} {'est. tok':>9} {'delta B':>9}")
    print("    " + "-" * 40)
    prev = None
    for i in range(6):
        history.append(message(f"msg-{i:04d}", 0 if i % 2 == 0 else 1,
                               [minimal_part(PAYLOADS["structured"])]))
        t = task("task-0001", "ctx-0001", 1, history=history)
        size = len(enc(t))
        delta = "" if prev is None else f"{size - prev:>9}"
        print(f"    {i + 1:>8} {size:>9} {estimate_tokens(enc(t)):>9} {delta:>9}")
        prev = size
    print("    -> history is carried wholesale; cost grows linearly with turns")

    # ---- 5. structured Part vs text Part ----------------------------------
    print("\n[5] Part form: `text` string vs `data` object (both schema-supported)")
    text_part = message("m", 0, [minimal_part(ARGS_JSON)])
    data_part = message("m", 0, [structured_part(ARGS)])
    print(f"    Part{{text: json string}} : {len(enc(text_part))} B  {enc(text_part)}")
    print(f"    Part{{data: object}}      : {len(enc(data_part))} B  {enc(data_part)}")
    delta = len(enc(data_part)) - len(enc(text_part))
    print(f"    -> `data` costs {delta} B MORE, because a structured Part must also")
    print("       carry `mediaType`. Its benefit is TYPE FIDELITY (no escaping, no")
    print("       re-parse ambiguity), NOT byte savings. Do not claim otherwise.")

    print("\n" + "=" * 78)
    print("INTERPRETATION")
    print("  * The envelope is the dominant term: ~87 B fixed per message, i.e.")
    print("    46-58% of a realistic message. Per-message payload tuning is")
    print("    therefore diluted -- an argument for fewer, larger messages.")
    print("  * Ranking is PRESERVED once the payload is serialised comparably")
    print("    (compact, as ArkTS JSON.stringify would): structured 164 B <")
    print("    summary 168 B < natural 205 B. So `structured` remains the")
    print("    cheapest form AND the lossless one, i.e. the truncating summary")
    print("    stays strictly dominated on the wire too.")
    print("  * `Task.history` is carried wholesale at ~133 B/turn: the A2A")
    print("    analogue of the context-growth problem this project attacks.")
    print("  * A2A natively supports structured Parts, so the natural-language")
    print("    default is a design choice, not a protocol constraint.")
    print()
    print("  NEEDS A REAL DEVICE to confirm: HSP proxy framing, the actual")
    print("  serialisation, and whether `history` is retransmitted per call.")
    print("  Until then this is a schema-level estimate, not a measurement.")
    print("=" * 78)


if __name__ == "__main__":
    main()
