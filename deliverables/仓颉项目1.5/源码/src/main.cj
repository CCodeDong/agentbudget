package agentbudget4cj

import std.collection.*
import std.console.*
import std.convert.*

// Command-line bridge for the experiment harness.
//
// The scheduler is the research artifact; the harness that drives tasks is
// written in Python. Rather than couple the two, the library ships a small
// line protocol so any driver can obtain a decision without linking Cangjie.
//
// PROTOCOL (one request per line on stdin; one response line per request)
//
//   request  <difficulty> <tier> <rttMs> <metered> <lan> <tokensSpent> <tokenCap> <cloudCallsLeft> <mode> <topK> [query...]
//              difficulty      Float64 in [0,1]
//              tier            wifi | cellular | weak | offline
//              rttMs           Int64
//              metered         0 | 1
//              lan             0 | 1   (edge inference node reachable on the LAN)
//              tokensSpent     Int64
//              tokenCap        Int64
//              cloudCallsLeft  Int64
//              mode            eager | budget  (REQUIRED - see note)
//              topK            Int64, tool-injection policy selector:
//                                <0 = score-driven adaptive, |topK| = threshold as a
//                                     percentage of the top retrieval score.
//                                     -50 (the default) is the proposed method.
//                                0  = BUDGET-driven adaptive. A baseline only --
//                                     measured to be dominated by a fixed k (§6.6),
//                                     so it must not be used as a default.
//                                >0 = pinned to that many full schemas (baselines)
//                              This is the direct knob between context size and
//                              retrieval recall, so the harness sweeps it.
//                              NOTE: topK == 0 here means the budget-driven policy,
//                              whereas kUsed == 0 in the response means "every tool
//                              was injected" (the eager path). The two zeroes are
//                              unrelated; `toolStrategy` is the disambiguator.
//              query           remainder of the line, spaces allowed
//
//   response <route>\t<msgForm>\t<toolStrategy>\t<toolTokens>\t<kUsed>\t<selectedTools>\t<reason>
//
// `kUsed` is 0 when every tool's full schema was injected, otherwise the number
// of tools that expose one. It is reported explicitly so an adaptive policy's
// choice is observable rather than inferred from a formatted string.
//
// `selectedTools` is a comma-separated list of the tools whose FULL schema is
// exposed. That set -- not the pool size -- determines whether a model can
// actually invoke a tool, so the harness needs it to assemble a faithful prompt.
//
// `mode` is positional and therefore mandatory: omitting it would be silently
// read as the first word of the query.
//
// Separators may be spaces or tabs. Carriage returns are tolerated so that a
// Windows shell pipeline behaves the same as a file with Unix line endings.
// A line that cannot be parsed yields "error\t<detail>" rather than a silently
// wrong measurement.
//
// Example:
//   "0.2 wifi 20 0 1 500 8000 10 budget 3 search my files for the report" | agentbudget4cj.exe

func parseTier(s: String): Option<NetTier> {
    match (s) {
        case "wifi" => Some(NetTier.Wifi)
        case "cellular" => Some(NetTier.Cellular)
        case "weak" => Some(NetTier.Weak)
        case "offline" => Some(NetTier.Offline)
        case _ => None
    }
}

func flag(s: String): Bool {
    return s == "1" || s == "true"
}

// Build a JSON Schema whose required list matches the tool's real parameters.
// A shared placeholder schema would make every tool claim the same required
// arguments, which would invalidate any downstream verification of tool calls.
func schemaFor(name: String, desc: String, params: Array<String>): String {
    let props = StringBuilder()
    let req = StringBuilder()
    var first = true
    for (p in params) {
        if (!first) {
            props.append(",")
            req.append(",")
        }
        props.append("\"")
        props.append(p)
        props.append("\":{\"type\":\"string\",\"description\":\"the ")
        props.append(p)
        props.append(" argument\"}")
        req.append("\"")
        req.append(p)
        req.append("\"")
        first = false
    }
    return "{\"name\":\"" + name + "\",\"description\":\"" + desc +
        " -- a verbose description mirroring what an MCP server really ships, " +
        "including usage notes that inflate the injected context\",\"inputSchema\":{\"type\":\"object\",\"properties\":{" +
        props.toString() + "},\"required\":[" + req.toString() + "]}}"
}

// A representative mobile tool pool. Kept self-contained so the bridge has no
// external inputs; the harness mirrors this pool exactly.
//
// The first five entries are the "real" tools that the task set targets; the
// remainder are distractors. An earlier experiment ran against only the first
// five and found compression to be free, which is exactly why the distractors
// exist -- a five-tool pool makes top-k retrieval trivially correct and hides
// the cost side entirely. That historical run is reproducible through the
// `pool` verb below, which is why the pool is not simply hardcoded.
func defaultPool(): ToolPool {
    let pool = ToolPool()
    pool.add(ToolSpec("calendar.create", "create a calendar event", ["title", "start"],
        schemaFor("calendar.create", "create a calendar event", ["title", "start"])))
    pool.add(ToolSpec("contact.lookup", "look up a contact by name", ["name"],
        schemaFor("contact.lookup", "look up a contact by name", ["name"])))
    pool.add(ToolSpec("file.search", "search files by keyword", ["query", "limit"],
        schemaFor("file.search", "search files by keyword", ["query", "limit"])))
    pool.add(ToolSpec("notice.send", "send a notification", ["text"],
        schemaFor("notice.send", "send a notification", ["text"])))
    pool.add(ToolSpec("web.search", "search the web", ["query", "limit"],
        schemaFor("web.search", "search the web", ["query", "limit"])))
    // Distractor tools. A five-tool pool makes top-k retrieval trivially
    // correct, which hides the cost side of context compression entirely.
    // These are plausible mobile capabilities chosen so that several of them
    // genuinely compete with the gold tools on lexical grounds.
    pool.add(ToolSpec("sms.send", "send a text message", ["to", "body"],
        schemaFor("sms.send", "send a text message", ["to", "body"])))
    pool.add(ToolSpec("email.compose", "compose an email", ["to", "subject", "body"],
        schemaFor("email.compose", "compose an email", ["to", "subject", "body"])))
    pool.add(ToolSpec("music.play", "play music by name", ["track"],
        schemaFor("music.play", "play music by name", ["track"])))
    pool.add(ToolSpec("map.navigate", "navigate to a destination", ["place"],
        schemaFor("map.navigate", "navigate to a destination", ["place"])))
    pool.add(ToolSpec("timer.set", "set a countdown timer", ["minutes"],
        schemaFor("timer.set", "set a countdown timer", ["minutes"])))
    pool.add(ToolSpec("alarm.create", "create an alarm", ["time"],
        schemaFor("alarm.create", "create an alarm", ["time"])))
    pool.add(ToolSpec("weather.query", "query the weather forecast", ["city"],
        schemaFor("weather.query", "query the weather forecast", ["city"])))
    pool.add(ToolSpec("translate.text", "translate text", ["text", "target"],
        schemaFor("translate.text", "translate text", ["text", "target"])))
    pool.add(ToolSpec("clipboard.read", "read the clipboard", [],
        schemaFor("clipboard.read", "read the clipboard", [])))
    pool.add(ToolSpec("battery.status", "report battery status", [],
        schemaFor("battery.status", "report battery status", [])))
    return pool
}

func planLine(line: String, pool: ToolPool): String {
    // Normalise every whitespace form we might receive, including the CR that a
    // Windows pipeline appends. `trimAscii` alone does not remove CR.
    let flat = line.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    let raw = flat.split(" ")
    let parts = ArrayList<String>()
    for (x in raw) {
        if (x.size > 0) {
            parts.add(x)
        }
    }

    if (10 > parts.size) {
        return "error\tneed 10 fields (through topK), got " + parts.size.toString() + " from [" + flat + "]"
    }

    let tier = match (parseTier(parts[1])) {
        case Some(t) => t
        case None => return "error\tunknown tier [" + parts[1] + "]"
    }

    var difficulty: Float64 = 0.0
    var rtt: Int64 = 0
    var tokensSpent: Int64 = 0
    var tokenCap: Int64 = 0
    var cloudLeft: Int64 = 0
    // Default -50 = score-driven adaptive at alpha = 50% of the top score.
    // This is the method the paper proposes (§6.7) and the policy the HarmonyOS
    // app ships. A positive value pins k to reproduce a baseline; 0 selects the
    // budget-driven policy, which is itself a reported baseline (§6.6) and must
    // NOT be the default -- it was measured to be dominated by a fixed k.
    // Experiments always pass this explicitly, so the default affects only
    // ad-hoc use of the CLI.
    var topK: Int64 = -50
    try {
        difficulty = Float64.parse(parts[0])
        rtt = Int64.parse(parts[2])
        tokensSpent = Int64.parse(parts[5])
        tokenCap = Int64.parse(parts[6])
        cloudLeft = Int64.parse(parts[7])
        topK = Int64.parse(parts[9])
    } catch (e: Exception) {
        return "error\tparse failed on [" + flat + "]: " + e.toString()
    }

    var mode = "budget"
    if (parts.size >= 9) {
        mode = parts[8]
    }

    // The query is the remainder of the line, so it may contain spaces. The
    // query matters because it drives lexical tool selection.
    var query = "search my files for the quarterly report"
    if (parts.size >= 11) {
        var q = ""
        var qi: Int64 = 10
        while (parts.size > qi) {
            if (q.size > 0) {
                q += " "
            }
            q += parts[qi]
            qi += 1
        }
        query = q
    }

    let net = NetState(tier, rtt, flag(parts[3]), flag(parts[4]))
    let ledger = Ledger(Budget(tokenCap, 60000, cloudLeft, 50000))
    ledger.charge(tokensSpent, 0, 0, 0)

    var s: Scheduler = BudgetScheduler(topK)
    if (mode == "eager") {
        s = EagerScheduler()
    }

    let plan = s.plan(query, difficulty, pool, net, ledger)

    // Report which tools expose a FULL schema, because that -- not the pool
    // size -- is what determines whether the model can actually invoke a tool.
    // `selectTopK` is pure, so recomputing the selection here cannot diverge
    // from the one the scheduler made.
    let selectedSb = StringBuilder()
    if (plan.kUsed == 0) {
        for (t in pool.all()) {
            selectedSb.append(t.name)
            selectedSb.append(",")
        }
    } else {
        for (t in pool.selectTopK(query, plan.kUsed)) {
            selectedSb.append(t.name)
            selectedSb.append(",")
        }
    }

    return plan.route.label() + "\t" + msgFormLabel(plan.msgForm) + "\t" + plan.toolReason +
        "\t" + plan.toolTokens.toString() + "\t" + plan.kUsed.toString() + "\t" +
        selectedSb.toString() + "\t" + plan.route.reason
}

// Agent-to-agent message rendering, exposed so the harness never reimplements
// the codec. The representation decision and its realisation both belong to the
// Cangjie artifact; if the harness rendered messages in Python the experiment
// would be measuring Python, not this library.
//
//   request  codec|<form>|<budget>|<from>|<to>|<intent>|<payload...>
//              form    natural | summary | structured
//              budget  character budget for the truncating `summary` form
//
//   response <rendered message>\t<token cost>
//
// The budget is a parameter rather than a constant so its effect can be swept:
// the report claims the truncating form is dominated, and that claim has to hold
// across budgets rather than at a single hand-picked value.
//
// The payload is the remainder of the line re-joined with "|", so a payload
// that itself contains "|" (as the structured form produces) round-trips.
func codecLine(line: String): String {
    let f = line.split("|")
    if (7 > f.size) {
        return "error\tcodec needs codec|form|budget|from|to|intent|payload"
    }
    var form = MsgForm.Natural
    match (f[1]) {
        case "natural" => form = MsgForm.Natural
        case "summary" => form = MsgForm.Summary
        case "structured" => form = MsgForm.Structured
        case _ => return "error\tunknown form [" + f[1] + "]"
    }
    var budget: Int64 = 40
    try {
        budget = Int64.parse(f[2])
    } catch (e: Exception) {
        return "error\tbad budget [" + f[2] + "]"
    }
    if (budget < 1) {
        budget = 1
    }

    var payload = ""
    var i: Int64 = 6
    while (f.size > i) {
        if (payload.size > 0) {
            payload += "|"
        }
        payload += f[i]
        i += 1
    }

    let codec = Codec(budget)
    let m = AgentMsg(f[3], f[4], f[5], payload)
    return codec.encode(m, form) + "\t" + codec.cost(m, form).toString()
}

/**
 * The pool restricted to its first `n` tools, in declaration order.
 *
 * `n <= 0` or `n >= size` returns the full pool. This exists so the early
 * five-tool experiment -- whose data the paper reports -- stays reproducible by
 * command rather than only by having happened to run before the pool grew.
 */
func poolWithLimit(n: Int64): ToolPool {
    let full = defaultPool()
    if (n <= 0 || n >= full.size()) {
        return full
    }
    let limited = ToolPool()
    var i: Int64 = 0
    for (t in full.all()) {
        if (i >= n) {
            break
        }
        limited.add(t)
        i += 1
    }
    return limited
}

main(): Int64 {
    var pool = poolWithLimit(0)
    var running = true
    while (running) {
        match (Console.stdIn.readln()) {
            case Some(line) =>
                let flat = line.replace("\r", "").replace("\n", "")
                if (flat.size > 0) {
                    if (flat == "quit" || flat == "exit") {
                        running = false
                    } else {
                        let head = flat.split("|")
                        if (head.size >= 7 && head[0] == "codec") {
                            println(codecLine(flat))
                        } else if (head.size == 2 && head[0] == "pool") {
                            // Stateful and deliberately separate from the plan
                            // line: adding a field there would shift the query
                            // remainder and break every existing caller.
                            var n: Int64 = 0
                            try {
                                n = Int64.parse(head[1])
                            } catch (e: Exception) {
                                n = 0
                            }
                            pool = poolWithLimit(n)
                            println("ok\tpool=" + pool.size().toString())
                        } else {
                            println(planLine(flat, pool))
                        }
                    }
                }
            case None => running = false
        }
    }
    return 0
}
