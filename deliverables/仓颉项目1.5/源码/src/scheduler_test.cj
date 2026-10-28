/**
 * Unit tests for the v0 core.
 *
 * Beyond basic correctness these encode the *invariants* the research depends
 * on: compression must actually reduce cost, and degradation must actually
 * trigger under budget pressure.
 */
package agentbudget4cj

import std.unittest.*
import std.unittest.testmacro.*
import std.collection.*

func sampleSchema(name: String): String {
    return "{\"name\":\"" + name + "\",\"description\":\"a fairly verbose tool description that " +
        "mirrors what an MCP server really ships\",\"inputSchema\":{\"type\":\"object\",\"properties\":" +
        "{\"query\":{\"type\":\"string\",\"description\":\"the search query\"}," +
        "\"limit\":{\"type\":\"integer\",\"description\":\"max results\"}}," +
        "\"required\":[\"query\"]}}"
}

func samplePool(): ToolPool {
    let pool = ToolPool()
    pool.add(ToolSpec("calendar.create", "create a calendar event", ["title", "start"], sampleSchema("calendar.create")))
    pool.add(ToolSpec("contact.lookup", "look up a contact by name", ["name"], sampleSchema("contact.lookup")))
    pool.add(ToolSpec("file.search", "search files by keyword", ["query", "limit"], sampleSchema("file.search")))
    pool.add(ToolSpec("notice.send", "send a notification", ["text"], sampleSchema("notice.send")))
    pool.add(ToolSpec("web.search", "search the web", ["query", "limit"], sampleSchema("web.search")))
    return pool
}

@Test
public func testEstimateTokensBasics() {
    @Expect(estimateTokens(""), 0)
    @Expect(estimateTokens("abcd"), 1)
    @Expect(estimateTokens("a") < estimateTokens("aaaaaaaa"), true)
}

@Test
public func testSummaryIsCheaperThanFullSchema() {
    let t = ToolSpec("calendar.create", "create a calendar event", ["title", "start"], sampleSchema("calendar.create"))
    @Expect(t.summaryTokens() < t.fullTokens(), true)
    @Expect(t.compressionRatio() < 1.0, true)
}

@Test
public func testSummaryPoolIsCheaperThanEager() {
    let pool = samplePool()
    let eager = estimateTokens(pool.eagerSchemas())
    let staged = estimateTokens(pool.stagedSchemas("search my files for the report", 2))
    @Expect(staged < eager, true)
}

@Test
public func testTopKSelectsRelevantTool() {
    let pool = samplePool()
    let picked = pool.selectTopK("search the web for news", 1)
    @Expect(picked.size, 1)
    @Expect(picked[0].name, "web.search")
}

@Test
public func testTopKRespectsK() {
    let pool = samplePool()
    @Expect(pool.selectTopK("anything", 3).size, 3)
    @Expect(pool.selectTopK("anything", 99).size, 5)
}

@Test
public func testLedgerAccounting() {
    let b = Budget(1000, 5000, 3, 2000)
    let l = Ledger(b)
    @Expect(l.withinBudget(), true)
    @Expect(l.tokensLeft(), 1000)
    l.charge(400, 100, 1, 50)
    @Expect(l.tokensLeft(), 600)
    @Expect(l.cloudCallsLeft(), 2)
    @Expect(l.withinBudget(), true)
    l.charge(4000, 0, 0, 0)
    @Expect(l.withinBudget(), false)
    @Expect(l.tokenUtilization() > 1.0, false)
}

@Test
public func testEagerSchedulerInjectsEverythingAndPrefersCloud() {
    let pool = samplePool()
    let l = Ledger(Budget(100000, 100000, 10, 100000))
    let net = NetState(NetTier.Wifi, 20, false, true)
    let plan = EagerScheduler().plan("search files", 0.9, pool, net, l)
    @Expect(plan.toolReason, "eager-all")
    @Expect(plan.toolTokens, estimateTokens(pool.eagerSchemas()))
    @Expect(plan.msgForm, MsgForm.Natural)
    @Expect(plan.route.target, RouteTarget.Cloud)
}

@Test
public func testBudgetSchedulerDegradesMessageFormUnderPressure() {
    let net = NetState(NetTier.Wifi, 20, false, true)
    let pool = samplePool()

    let fresh = Ledger(Budget(10000, 100000, 10, 100000))
    @Expect(BudgetScheduler(3).plan("search files", 0.2, pool, net, fresh).msgForm, MsgForm.Natural)

    let half = Ledger(Budget(10000, 100000, 10, 100000))
    half.charge(4000, 0, 0, 0)
    @Expect(BudgetScheduler(3).plan("search files", 0.2, pool, net, half).msgForm, MsgForm.Summary)

    let tight = Ledger(Budget(10000, 100000, 10, 100000))
    tight.charge(7000, 0, 0, 0)
    @Expect(BudgetScheduler(3).plan("search files", 0.2, pool, net, tight).msgForm, MsgForm.Structured)
}

@Test
public func testBudgetSchedulerSwitchesToStagedWhenTight() {
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    let fresh = Ledger(Budget(10000, 100000, 10, 100000))
    @Expect(BudgetScheduler(3).plan("search files", 0.2, pool, net, fresh).toolReason, "eager")

    let tight = Ledger(Budget(10000, 100000, 10, 100000))
    tight.charge(8000, 0, 0, 0)
    @Expect(BudgetScheduler(3).plan("search files", 0.2, pool, net, tight).toolReason, "two-stage-top3")
}

@Test
public func testOfflineForcesOnDevice() {
    let pool = samplePool()
    let l = Ledger(Budget(10000, 100000, 10, 100000))
    let offline = NetState(NetTier.Offline, 0, false, false)
    @Expect(BudgetScheduler(3).plan("search files", 0.9, pool, offline, l).route.target, RouteTarget.OnDevice)
    @Expect(EagerScheduler().plan("search files", 0.9, pool, offline, l).route.target, RouteTarget.OnDevice)
}

@Test
public func testEdgeTierUsedWhenStepIsNotHard() {
    let pool = samplePool()
    let l = Ledger(Budget(10000, 100000, 10, 100000))
    let net = NetState(NetTier.Wifi, 20, false, true)
    // Low difficulty: no reason to spend a wide-area call, so the edge node wins.
    @Expect(BudgetScheduler(3).plan("search files", 0.2, pool, net, l).route.target, RouteTarget.Edge)
}

@Test
public func testEdgeSurvivesWideAreaFailure() {
    // The central reason an edge tier exists: the LAN stays up when the
    // wide-area link degrades, so an edge node is the only surviving remote
    // option. Without it, the step must fall all the way back to the device.
    let pool = samplePool()
    let net = NetState(NetTier.Weak, 1500, true, true)
    let l = Ledger(Budget(10000, 100000, 10, 100000))
    @Expect(BudgetScheduler(3).plan("search files", 0.9, pool, net, l).route.target, RouteTarget.Edge)

    let noLan = NetState(NetTier.Weak, 1500, true, false)
    @Expect(BudgetScheduler(3).plan("search files", 0.9, pool, noLan, l).route.target, RouteTarget.OnDevice)
}

@Test
public func testStructuredMessageIsCheaperThanNatural() {
    let codec = Codec(40)
    let m = AgentMsg("planner", "executor", "instruction", "find the quarterly report and summarise the revenue section")
    @Expect(codec.cost(m, MsgForm.Structured) < codec.cost(m, MsgForm.Natural), true)
    @Expect(codec.cost(m, MsgForm.Summary) < codec.cost(m, MsgForm.Natural), true)
}

@Test
public func testTruncateRunesIsSafe() {
    @Expect(truncateRunes("abcdef", 3), "abc")
    @Expect(truncateRunes("abc", 10), "abc")
    @Expect(truncateRunes("abc", 0), "")
    // Multi-byte characters must not be split.
    let cn = "把明天的会议改到下午三点"
    @Expect(truncateRunes(cn, 2), "把明")
}

// ---------------------------------------------------------------------------
// Placement predicates.
//
// These cover `router.cj`, which carried the weakest branch coverage of the
// decision-logic files. That mattered more than the number suggests: `edgeViable`
// ignoring the wide-area tier IS the paper's placement claim, and a branch that
// is never exercised is a claim that is never tested.
// ---------------------------------------------------------------------------

@Test
public func testCloudViableForEveryTier() {
    // Wifi is always viable; weak and offline never are.
    @Expect(NetState(NetTier.Wifi, 900, true, false).cloudViable(), true)
    @Expect(NetState(NetTier.Weak, 20, false, true).cloudViable(), false)
    @Expect(NetState(NetTier.Offline, 0, false, false).cloudViable(), false)
}

@Test
public func testCloudViableCellularRttBoundary() {
    // Cellular depends on the round trip, with 400 ms as the inclusive bound.
    @Expect(NetState(NetTier.Cellular, 399, true, false).cloudViable(), true)
    @Expect(NetState(NetTier.Cellular, 400, true, false).cloudViable(), true)
    @Expect(NetState(NetTier.Cellular, 401, true, false).cloudViable(), false)
    @Expect(NetState(NetTier.Cellular, 2000, true, false).cloudViable(), false)
}

@Test
public func testEdgeViableIsIndependentOfWideAreaTier() {
    // The central placement claim: LAN reachability does not depend on the
    // wide-area tier, so a weak or dead cellular link must NOT remove the edge
    // option. A baseline that conflates the two falls back to the device.
    for (tier in [NetTier.Wifi, NetTier.Cellular, NetTier.Weak, NetTier.Offline]) {
        @Expect(NetState(tier, 2000, true, true).edgeViable(), true)
        @Expect(NetState(tier, 20, false, false).edgeViable(), false)
    }
}

@Test
public func testNetTierLabelsAreDistinct() {
    let seen = HashSet<String>()
    for (tier in [NetTier.Wifi, NetTier.Cellular, NetTier.Weak, NetTier.Offline]) {
        let l = NetState(tier, 0, false, false).label()
        @Expect(seen.contains(l), false)
        seen.add(l)
    }
    @Expect(seen.size, 4)
}

@Test
public func testRouteDecisionLabelsAreDistinct() {
    let seen = HashSet<String>()
    for (t in [RouteTarget.OnDevice, RouteTarget.Edge, RouteTarget.Cloud]) {
        let l = RouteDecision(t, "why").label()
        @Expect(seen.contains(l), false)
        seen.add(l)
    }
    @Expect(seen.size, 3)
}

// ---------------------------------------------------------------------------
// The two adaptive policies and the eager baseline.
//
// Both adaptive functions previously had ZERO test coverage, including
// `adaptiveKByScore` -- the method the paper actually proposes. That is the same
// defect class as an untested placement predicate: a claim nothing executes is a
// claim nothing checks.
//
// The reason they were unreachable: `plan()` short-circuits to the eager path
// while utilisation is below 0.5 and full injection still fits, so a fresh ledger
// never reaches the adaptive code at all. The policies only run under budget
// pressure -- which is precisely the condition the paper is about.
// ---------------------------------------------------------------------------

/** A ledger already under pressure, so `plan()` cannot take the eager shortcut. */
func pressedLedger(): Ledger {
    let l = Ledger(Budget(8000, 60000, 10, 50000))
    l.charge(4800, 0, 0, 0)   // 60% used
    return l
}

@Test
public func testSchedulerNames() {
    @Expect(EagerScheduler().name(), "eager-mcp-default")
    @Expect(BudgetScheduler(3).name(), "budget-joint")
}

@Test
public func testMsgFormLabelCoversEveryForm() {
    @Expect(msgFormLabel(MsgForm.Natural), "natural")
    @Expect(msgFormLabel(MsgForm.Summary), "summary")
    @Expect(msgFormLabel(MsgForm.Structured), "structured")
}

@Test
public func testStepPlanDescribeReportsEveryField() {
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    let p = BudgetScheduler(3).plan("search files", 0.2, pool, net, pressedLedger())
    let d = p.describe()
    @Expect(d.contains("tools="), true)
    @Expect(d.contains("k="), true)
    @Expect(d.contains("tokens="), true)
    @Expect(d.contains("msg="), true)
    @Expect(d.contains("route="), true)
}

@Test
public func testEagerSchedulerReportsFullPoolAndNaturalForm() {
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    let l = Ledger(Budget(8000, 60000, 10, 50000))
    let p = EagerScheduler().plan("search files", 0.9, pool, net, l)
    @Expect(p.msgForm, MsgForm.Natural)
    @Expect(p.toolReason, "eager-all")
    // The eager scheduler reports kUsed == pool size, because every tool really
    // does expose a full schema on that path.
    @Expect(p.kUsed, pool.size())
}

@Test
public func testFreshLedgerTakesTheEagerShortcut() {
    // Pins the behaviour that kept the adaptive code unreachable: with headroom,
    // the scheduler declines to compress at all and reports kUsed == 0.
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    let fresh = Ledger(Budget(8000, 60000, 10, 50000))
    let p = BudgetScheduler(-50).plan("search files", 0.2, pool, net, fresh)
    @Expect(p.toolReason, "eager")
    @Expect(p.kUsed, 0)
}

@Test
public func testScoreDrivenAdaptiveKRespondsToAmbiguity() {
    // A query naming one tool unambiguously should expose no more schemas than
    // one whose words are scattered across the catalogue. This is the property
    // the paper's proposal rests on, so it is asserted rather than assumed.
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    let narrow = BudgetScheduler(-50).plan("look up a contact", 0.5, pool, net, pressedLedger())
    let wide = BudgetScheduler(-50).plan("search the web and notify a contact", 0.5, pool, net, pressedLedger())
    @Expect(narrow.kUsed >= 1, true)
    @Expect(wide.kUsed >= narrow.kUsed, true)
    @Expect(wide.kUsed <= pool.size(), true)
}

@Test
public func testScoreDrivenAdaptiveKIsClampedToPool() {
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    // alpha = 1% makes the threshold minimally restrictive, so the clamp is what
    // keeps k inside the pool rather than the threshold.
    let p = BudgetScheduler(-1).plan("search the web for news", 0.5, pool, net, pressedLedger())
    @Expect(p.kUsed >= 1, true)
    @Expect(p.kUsed <= pool.size(), true)
}

@Test
public func testScoreDrivenAdaptiveKFallsBackWithoutLexicalSignal() {
    // No query word matches any tool, so the score distribution carries no
    // information and the policy must fall back rather than pretend to decide.
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    let p = BudgetScheduler(-50).plan("zzz qqq wwww", 0.5, pool, net, pressedLedger())
    @Expect(p.kUsed, 5)
}

@Test
public func testBudgetDrivenAdaptiveKSaturatesAndClamps() {
    let pool = samplePool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    // The policy's intent: with LESS budget left, expose fewer or equal schemas.
    // So k must be non-increasing as `spent` grows. This is the policy the paper
    // measures to be dominated, so its behaviour needs pinning precisely --
    // otherwise "dominated" could be an artefact of the clamp rather than of the
    // signal.
    var prev: Int64 = 99
    for (spent in [4800, 6000, 7000, 7800]) {
        let l = Ledger(Budget(8000, 60000, 10, 50000))
        l.charge(spent, 0, 0, 0)
        let k = BudgetScheduler(0).plan("search files", 0.5, pool, net, l).kUsed
        @Expect(k <= prev, true)
        @Expect(k >= 1, true)
        @Expect(k <= pool.size(), true)
        prev = k
    }
}

@Test
public func testEmptyPoolDoesNotCrash() {
    // The guard exists in both adaptive functions; an empty pool is reachable in
    // the app when the tool catalogue fails to load. Pressure is applied so the
    // adaptive paths are the ones under test.
    let empty = ToolPool()
    let net = NetState(NetTier.Wifi, 20, false, true)
    @Expect(BudgetScheduler(0).plan("anything", 0.5, empty, net, pressedLedger()).kUsed >= 0, true)
    @Expect(BudgetScheduler(-50).plan("anything", 0.5, empty, net, pressedLedger()).kUsed >= 0, true)
    @Expect(BudgetScheduler(3).plan("anything", 0.5, empty, net, pressedLedger()).toolTokens, 0)
}
