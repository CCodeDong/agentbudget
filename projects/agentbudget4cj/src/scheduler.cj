/**
 * The joint scheduler: the core artifact of this project.
 *
 * Existing work decides tool injection, message representation and on-device
 * vs cloud placement *separately*. Here all three are decided together against
 * one explicit budget, which is the claim this code has to earn.
 */
package agentbudget4cj

/** Everything a scheduler decided for one step, plus why. */
public struct StepPlan {
    public let toolContext: String
    public let toolTokens: Int64
    public let toolReason: String
    /**
     * How many tools expose a full schema this step.
     *
     * Reported explicitly rather than inferred from `toolReason` so an external
     * driver can observe what an adaptive policy actually chose -- the whole
     * point of adaptive k is that the choice varies, and a string that has to be
     * parsed is a poor interface for a quantity under study.
     * 0 means every tool was injected (the eager path).
     */
    public let kUsed: Int64
    public let msgForm: MsgForm
    public let route: RouteDecision

    public init(
        toolContext: String,
        toolTokens: Int64,
        toolReason: String,
        kUsed: Int64,
        msgForm: MsgForm,
        route: RouteDecision
    ) {
        this.toolContext = toolContext
        this.toolTokens = toolTokens
        this.toolReason = toolReason
        this.kUsed = kUsed
        this.msgForm = msgForm
        this.route = route
    }

    /** One-line audit record, suitable for experiment logs. */
    public func describe(): String {
        return "tools=" + this.toolReason + " k=" + this.kUsed.toString() +
            " tokens=" + this.toolTokens.toString() +
            " msg=" + msgFormLabel(this.msgForm) + " route=" + this.route.label() +
            " (" + this.route.reason + ")"
    }
}

public func msgFormLabel(f: MsgForm): String {
    match (f) {
        case Natural => "natural"
        case Summary => "summary"
        case Structured => "structured"
    }
}

/** Pluggable scheduling policy. */
public interface Scheduler {
    func name(): String
    func plan(query: String, difficulty: Float64, pool: ToolPool, net: NetState, ledger: Ledger): StepPlan
}

/**
 * Baseline `S1`: the eager, MCP-default behaviour.
 *
 * Every tool's full schema is injected every step, messages are natural
 * language, and the cloud is preferred whenever it is reachable. This is the
 * straw man the project measures against, kept honest and unoptimised.
 */
public class EagerScheduler <: Scheduler {
    public init() {}

    public func name(): String {
        return "eager-mcp-default"
    }

    public func plan(query: String, difficulty: Float64, pool: ToolPool, net: NetState, ledger: Ledger): StepPlan {
        let ctx = pool.eagerSchemas()
        var target = RouteTarget.OnDevice
        var reason = "network " + net.label() + " unusable"
        if (net.cloudViable() && ledger.cloudCallsLeft() > 0) {
            target = RouteTarget.Cloud
            reason = "cloud preferred"
        }
        return StepPlan(ctx, estimateTokens(ctx), "eager-all", pool.size(), MsgForm.Natural,
            RouteDecision(target, reason))
    }
}

/**
 * The budget-aware joint scheduler.
 *
 * Degradation order is deliberate and follows the measured cost structure:
 * message representation is the cheapest to compress with the least task risk,
 * then tool schemas, then placement.
 *
 * `stagedK <= 0` selects ADAPTIVE top-k. The k sweep showed that a fixed k is
 * suboptimal in a way the scheduler can actually see: k must be large enough to
 * keep the correct tool in the injected set, but every extra schema is context
 * spent whether or not it is used. Making k a function of the remaining budget
 * is what turns "jointly decide" from a claim into a measurement.
 */
public class BudgetScheduler <: Scheduler {
    private let stagedK: Int64

    public init(stagedK: Int64) {
        this.stagedK = stagedK
    }

    public func name(): String {
        return "budget-joint"
    }

    /**
     * Choose k from the budget actually available, using the pool's own
     * measured average schema cost rather than an assumed constant.
     *
     * At most half the remaining headroom is spent on full schemas; the rest is
     * left for the model's reasoning and reply, which the experiments showed is
     * the binding constraint once the context is compressed.
     */
    private func adaptiveK(pool: ToolPool, tokensLeft: Int64): Int64 {
        let n = pool.size()
        if (n <= 0) {
            return 0
        }
        let avg = estimateTokens(pool.eagerSchemas()) / n
        if (avg <= 0) {
            return 1
        }
        var k = (tokensLeft / 2) / avg
        if (k < 1) {
            k = 1
        }
        // Beyond roughly eight tools the retrieval gain flattens while the cost
        // keeps rising, so the cap is a domain bound rather than a budget one.
        if (k > 8) {
            k = 8
        }
        if (k > n) {
            k = n
        }
        return k
    }

    /**
     * Choose k from the SHAPE of the retrieval score distribution.
     *
     * Include every tool whose score reaches `alphaPct` percent of the top
     * score. This is the signal the budget-driven rule lacked: when one tool
     * dominates the scores the choice is unambiguous and a small k is safe; when
     * several tools score alike the query is ambiguous, and a larger k is needed
     * to keep the correct tool inside the injected set.
     *
     * `alphaPct` is a parameter rather than a constant because it is an
     * uncalibrated hyper-parameter, and a claim that rests on one hand-picked
     * value is fragile. Encoding it in the policy selector keeps the protocol
     * unchanged.
     *
     * If no tool scores above zero there is no lexical signal at all and the
     * distribution carries no information, so a fixed value is used rather than
     * pretending to decide.
     */
    private func adaptiveKByScore(pool: ToolPool, query: String, alphaPct: Int64): Int64 {
        let n = pool.size()
        if (n <= 0) {
            return 0
        }
        let scores = pool.scoreAll(query)
        if (scores.size == 0) {
            return 0
        }
        var top: Int64 = 0
        for (s in scores) {
            if (s > top) {
                top = s
            }
        }
        if (top <= 0) {
            return 5
        }
        // Ceiling, not truncation. The previous hand-written form was
        // (top + 1) / 2, which rounds up; a truncating percentage would silently
        // change behaviour at the same nominal alpha and invalidate every
        // measurement taken with the earlier formula.
        var threshold = (top * alphaPct + 99) / 100
        if (threshold < 1) {
            threshold = 1
        }
        var k: Int64 = 0
        for (s in scores) {
            if (s >= threshold) {
                k += 1
            }
        }
        if (k < 1) {
            k = 1
        }
        if (k > 8) {
            k = 8
        }
        if (k > n) {
            k = n
        }
        return k
    }

    public func plan(query: String, difficulty: Float64, pool: ToolPool, net: NetState, ledger: Ledger): StepPlan {
        let util = ledger.tokenUtilization()
        let tokensLeft = ledger.tokensLeft()

        // ---- 1. tool injection ----
        let eagerCtx = pool.eagerSchemas()
        let eagerTokens = estimateTokens(eagerCtx)
        var toolContext = ""
        var toolReason = ""
        var kUsed: Int64 = 0
        if (util < 0.5 && eagerTokens * 3 <= tokensLeft) {
            toolContext = eagerCtx
            toolReason = "eager"
            kUsed = 0
        } else {
            var k = this.stagedK
            if (k == 0) {
                k = this.adaptiveK(pool, tokensLeft)
            } else if (k < 0) {
                // Negative k selects the score-driven policy, with |k| as the
                // threshold expressed in percent of the top score. Encoding the
                // hyper-parameter here keeps the wire protocol unchanged.
                var alphaPct = -k
                if (alphaPct < 1) {
                    alphaPct = 1
                }
                if (alphaPct > 100) {
                    alphaPct = 100
                }
                k = this.adaptiveKByScore(pool, query, alphaPct)
            }
            kUsed = k
            toolContext = pool.stagedSchemas(query, k)
            toolReason = "two-stage-top" + k.toString()
        }
        let toolTokens = estimateTokens(toolContext)

        // ---- 2. message representation ----
        var form = MsgForm.Natural
        if (util >= 0.6) {
            form = MsgForm.Structured
        } else if (util >= 0.3) {
            form = MsgForm.Summary
        }

        // ---- 3. placement across three tiers, under the same budget ----
        // Priority: cloud only for genuinely hard steps with headroom left;
        // otherwise fall to the edge node, which stays reachable on the LAN
        // even when the wide-area link is weak or down.
        var target = RouteTarget.OnDevice
        var routeReason = "no remote tier viable"
        if (net.cloudViable() && ledger.cloudCallsLeft() > 0 && difficulty >= 0.6 && util < 0.8) {
            target = RouteTarget.Cloud
            routeReason = "hard step, wide-area viable, headroom left"
        } else if (net.edgeViable()) {
            target = RouteTarget.Edge
            routeReason = "edge reachable on LAN"
            if (!net.cloudViable()) {
                routeReason = "wide-area " + net.label() + " unusable; LAN survives"
            }
        }

        return StepPlan(toolContext, toolTokens, toolReason, kUsed, form,
            RouteDecision(target, routeReason))
    }
}
