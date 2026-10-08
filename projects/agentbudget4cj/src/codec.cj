/**
 * Inter-agent message representation (research gap: communication cost).
 *
 * In a multi-agent system running on a *single* device, natural-language
 * messages pay the full token cost of prose while gaining none of the
 * generality that prose buys across heterogeneous systems. This module makes
 * the representation an explicit, measurable choice.
 */
package agentbudget4cj

import std.deriving.*

/** How an agent-to-agent message is rendered on the wire / in context. */
@Derive[Equatable, ToString]
public enum MsgForm {
    | Natural
    | Summary
    | Structured
}

/** A single directed message between two agents. */
public struct AgentMsg {
    public let from: String
    public let to: String
    public let intent: String
    public let payload: String

    public init(from: String, to: String, intent: String, payload: String) {
        this.from = from
        this.to = to
        this.intent = intent
        this.payload = payload
    }
}

/** Truncate to at most `maxRunes` characters, never splitting a character. */
public func truncateRunes(s: String, maxRunes: Int64): String {
    if (maxRunes <= 0) {
        return ""
    }
    let rs = s.toRuneArray()
    if (rs.size <= maxRunes) {
        return s
    }
    var out = ""
    var i: Int64 = 0
    while (i < maxRunes) {
        out += rs[i].toString()
        i += 1
    }
    return out
}

/**
 * Renders `AgentMsg` in one of three forms.
 *
 * `Structured` uses short field codes and a delimiter rather than prose, which
 * is the end of the spectrum we expect to win on cost -- at the risk of small
 * models failing to parse it. Quantifying that failure rate is a research
 * question, so the codec never silently falls back: the caller decides.
 */
public class Codec {
    private let summaryCharBudget: Int64

    public init(summaryCharBudget: Int64) {
        this.summaryCharBudget = summaryCharBudget
    }

    public func encode(m: AgentMsg, form: MsgForm): String {
        match (form) {
            case Natural =>
                "Agent " + m.from + " is sending the following " + m.intent +
                " to agent " + m.to + ": " + m.payload
            case Summary =>
                "[" + m.from + "->" + m.to + "] " + m.intent + ": " +
                truncateRunes(m.payload, this.summaryCharBudget)
            case Structured =>
                m.from + "|" + m.to + "|" + m.intent + "|" + m.payload
        }
    }

    /** Estimated token cost of a message under a given form. */
    public func cost(m: AgentMsg, form: MsgForm): Int64 {
        return estimateTokens(this.encode(m, form))
    }
}
