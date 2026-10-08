/**
 * Budget primitives for on-device multi-agent scheduling.
 *
 * The central claim of the project: on a mobile device the binding constraint
 * is a *joint* budget over tokens, latency, cloud calls and traffic, not any
 * single one of them. Everything downstream is expressed against `Ledger`.
 */
package agentbudget4cj

/**
 * Heuristic token estimator.
 *
 * Calibrated against a real tokenizer later; for now it separates ASCII from
 * non-ASCII because CJK text costs roughly 1 token per character while ASCII
 * costs roughly a quarter of that. Kept deliberately dependency-free so the
 * library stays usable without stdx.
 */
public func estimateTokens(s: String): Int64 {
    var ascii: Int64 = 0
    var wide: Int64 = 0
    for (b in s.toArray()) {
        if (b < 128) {
            ascii += 1
        } else {
            wide += 1
        }
    }
    // ASCII bytes: ~4 bytes per token. Non-ASCII bytes: treat each byte as
    // roughly a third of a token so that a 3-byte CJK char lands near 1 token.
    return ascii / 4 + (wide + 2) / 3
}

/** Hard caps for one task episode. */
public struct Budget {
    public let tokenCap: Int64
    public let latencyCapMs: Int64
    public let cloudCallCap: Int64
    public let trafficCapKb: Int64

    public init(tokenCap: Int64, latencyCapMs: Int64, cloudCallCap: Int64, trafficCapKb: Int64) {
        this.tokenCap = tokenCap
        this.latencyCapMs = latencyCapMs
        this.cloudCallCap = cloudCallCap
        this.trafficCapKb = trafficCapKb
    }
}

/**
 * Mutable accounting for a single episode.
 *
 * `charge` is intentionally the only mutator so that every policy decision can
 * be audited against a single, explicit cost record.
 */
public class Ledger {
    private let budget: Budget
    public var tokensSpent: Int64 = 0
    public var latencySpentMs: Int64 = 0
    public var cloudCalls: Int64 = 0
    public var trafficSpentKb: Int64 = 0

    public init(budget: Budget) {
        this.budget = budget
    }

    public func getBudget(): Budget {
        return this.budget
    }

    public func charge(tokens: Int64, latencyMs: Int64, cloudCalls: Int64, trafficKb: Int64): Unit {
        this.tokensSpent += tokens
        this.latencySpentMs += latencyMs
        this.cloudCalls += cloudCalls
        this.trafficSpentKb += trafficKb
    }

    public func tokensLeft(): Int64 {
        return this.budget.tokenCap - this.tokensSpent
    }

    public func latencyLeftMs(): Int64 {
        return this.budget.latencyCapMs - this.latencySpentMs
    }

    public func cloudCallsLeft(): Int64 {
        return this.budget.cloudCallCap - this.cloudCalls
    }

    public func trafficLeftKb(): Int64 {
        return this.budget.trafficCapKb - this.trafficSpentKb
    }

    /** True while every dimension still has headroom. */
    public func withinBudget(): Bool {
        return this.tokensLeft() >= 0 &&
            this.latencyLeftMs() >= 0 &&
            this.cloudCallsLeft() >= 0 &&
            this.trafficLeftKb() >= 0
    }

    /** Fraction of the token budget consumed, clamped to [0, 1]. */
    public func tokenUtilization(): Float64 {
        if (this.budget.tokenCap <= 0) {
            return 1.0
        }
        let u = Float64(this.tokensSpent) / Float64(this.budget.tokenCap)
        if (u < 0.0) {
            return 0.0
        }
        if (u > 1.0) {
            return 1.0
        }
        return u
    }
}
