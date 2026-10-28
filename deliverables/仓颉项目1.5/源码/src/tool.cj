package agentbudget4cj

import std.collection.*

public struct ToolSpec {
    public let name: String
    public let oneLine: String
    public let paramNames: Array<String>
    public let fullSchema: String

    // Cached normalised forms.
    //
    // The lexical scorer runs on every agent step against an immutable pool, so
    // lower-casing the same three strings on each call is pure waste. Caching
    // them here is what makes the per-step selection cost acceptable; the
    // remaining work is then only the query itself.
    private let nameLower: String
    private let descLower: String
    private let paramLower: String

    public init(name: String, oneLine: String, paramNames: Array<String>, fullSchema: String) {
        this.name = name
        this.oneLine = oneLine
        this.paramNames = paramNames
        this.fullSchema = fullSchema
        this.nameLower = name.toAsciiLower()
        this.descLower = oneLine.toAsciiLower()
        let sb = StringBuilder()
        for (p in paramNames) {
            sb.append(" ")
            sb.append(p.toAsciiLower())
        }
        this.paramLower = sb.toString()
    }

    public func getParamLower(): String {
        return this.paramLower
    }

    public func getNameLower(): String {
        return this.nameLower
    }

    public func getDescLower(): String {
        return this.descLower
    }

    public func summaryTokens(): Int64 {
        var params = ""
        for (p in this.paramNames) {
            params += p + ","
        }
        return estimateTokens(this.name + " " + this.oneLine + " " + params)
    }

    public func fullTokens(): Int64 {
        return estimateTokens(this.fullSchema)
    }

    public func compressionRatio(): Float64 {
        let f = this.fullTokens()
        if (f <= 0) {
            return 1.0
        }
        return Float64(this.summaryTokens()) / Float64(f)
    }
}

// Stopwords are dropped, and repeated words are counted once.
//
// Measured motivation: the first version scored every occurrence of every query
// word. In "search my contact list for the person from the vendor" the word
// "the" appears twice, so any tool whose description merely contains "the"
// collected +6 and outranked the correct `contact.lookup`. That single artefact
// accounted for the *entire* accuracy loss of the compressed arm -- which is
// why retrieval has to be normalised before compression is blamed for it.
func isStopword(w: String): Bool {
    match (w) {
        case "the" => true
        case "a" => true
        case "an" => true
        case "and" => true
        case "for" => true
        case "from" => true
        case "with" => true
        case "about" => true
        case "that" => true
        case "this" => true
        case "my" => true
        case "me" => true
        case "to" => true
        case "of" => true
        case "in" => true
        case "on" => true
        case "at" => true
        case "is" => true
        case "it" => true
        case "up" => true
        case "get" => true
        case "look" => true
        case "please" => true
        case "next" => true
        case "last" => true
        case _ => false
    }
}

func normalizeQueryWords(qLower: String): ArrayList<String> {
    let seen = HashSet<String>()
    let words = ArrayList<String>()
    for (w in qLower.split(" ")) {
        if (w.size >= 2 && !isStopword(w) && !seen.contains(w)) {
            seen.add(w)
            words.add(w)
        }
    }
    return words
}

public class ToolPool {
    private let tools: ArrayList<ToolSpec>

    public init() {
        this.tools = ArrayList<ToolSpec>()
    }

    public func add(t: ToolSpec): Unit {
        this.tools.add(t)
    }

    public func size(): Int64 {
        return this.tools.size
    }

    public func all(): ArrayList<ToolSpec> {
        return this.tools
    }

    // Baseline S1: advertise every tool, as an eager MCP client does.
    public func eagerSchemas(): String {
        let sb = StringBuilder()
        for (t in this.tools) {
            sb.append(t.fullSchema)
        }
        return sb.toString()
    }

    // Compact summary pool: names, one-line descriptions and parameter names.
    public func summaryPool(): String {
        let sb = StringBuilder()
        for (t in this.tools) {
            sb.append("- ")
            sb.append(t.name)
            sb.append(": ")
            sb.append(t.oneLine)
            for (p in t.paramNames) {
                sb.append(" ")
                sb.append(p)
            }
            sb.append("\n")
        }
        return sb.toString()
    }

    // Naive lexical relevance over an already-normalised query.
    private func scorePrepared(t: ToolSpec, qLower: String, words: ArrayList<String>): Int64 {
        var s: Int64 = 0
        if (qLower.contains(t.getNameLower())) {
            s += 10
        }
        for (word in words) {
            if (t.getDescLower().contains(word)) {
                s += 3
            }
            if (t.getParamLower().contains(word)) {
                s += 1
            }
        }
        return s
    }

    // Top-k by lexical relevance, ties broken by pool order.
    // Partial selection: k linear scans, no sorted copy allocated.
    public func selectTopK(query: String, k: Int64): ArrayList<ToolSpec> {
        let qLower = query.toAsciiLower()
        let words = normalizeQueryWords(qLower)
        return this.selectTopKPrepared(qLower, words, k)
    }

    /**
     * Relevance score of every tool, in pool order.
     *
     * Exposed so a scheduling policy can reason about the SHAPE of the score
     * distribution rather than about how many tokens happen to be left. The
     * budget-driven adaptive rule was measured to be dominated by a fixed k
     * precisely because budget says nothing about whether retrieval is easy;
     * this is the signal that does.
     */
    public func scoreAll(query: String): ArrayList<Int64> {
        let qLower = query.toAsciiLower()
        let words = normalizeQueryWords(qLower)
        let scores = ArrayList<Int64>()
        for (t in this.tools) {
            scores.add(this.scorePrepared(t, qLower, words))
        }
        return scores
    }

    public func selectTopKPrepared(qLower: String, words: ArrayList<String>, k: Int64): ArrayList<ToolSpec> {
        let picked = ArrayList<ToolSpec>()
        let n = this.tools.size
        if (k <= 0 || n == 0) {
            return picked
        }

        let scores = ArrayList<Int64>()
        for (t in this.tools) {
            scores.add(this.scorePrepared(t, qLower, words))
        }

        let used = ArrayList<Bool>()
        var i: Int64 = 0
        while (n > i) {
            used.add(false)
            i += 1
        }

        var taken: Int64 = 0
        while (k > taken && n > taken) {
            var best: Int64 = -1
            var bestScore: Int64 = -1
            var j: Int64 = 0
            while (n > j) {
                if (!used[j] && scores[j] > bestScore) {
                    bestScore = scores[j]
                    best = j
                }
                j += 1
            }
            if (0 > best) {
                break
            }
            used[best] = true
            picked.add(this.tools[best])
            taken += 1
        }
        return picked
    }

    // Two-stage load: full schemas only for the selected tools.
    public func stagedSchemas(query: String, k: Int64): String {
        let qLower = query.toAsciiLower()
        let words = normalizeQueryWords(qLower)
        let sb = StringBuilder()
        sb.append(this.summaryPool())
        sb.append("\n")
        for (t in this.selectTopKPrepared(qLower, words, k)) {
            sb.append(t.fullSchema)
        }
        return sb.toString()
    }
}
