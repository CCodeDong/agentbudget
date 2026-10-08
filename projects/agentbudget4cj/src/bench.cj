/**
 * Micro-benchmarks for the v0 core.
 *
 * These exist to prove the *measurement pipeline* works end to end:
 * `cjpm bench --report-format=csv` is the intended source of the performance
 * tables in the course report and the paper, so it must be validated early
 * rather than discovered broken in week 14.
 */
package agentbudget4cj

import std.unittest.*
import std.unittest.testmacro.*

func benchSchema(name: String): String {
    return "{\"name\":\"" + name + "\",\"description\":\"a fairly verbose tool description that " +
        "mirrors what an MCP server really ships\",\"inputSchema\":{\"type\":\"object\",\"properties\":" +
        "{\"query\":{\"type\":\"string\",\"description\":\"the search query\"}," +
        "\"limit\":{\"type\":\"integer\",\"description\":\"max results\"}}," +
        "\"required\":[\"query\"]}}"
}

func benchPool(): ToolPool {
    let pool = ToolPool()
    pool.add(ToolSpec("calendar.create", "create a calendar event", ["title", "start"], benchSchema("calendar.create")))
    pool.add(ToolSpec("contact.lookup", "look up a contact by name", ["name"], benchSchema("contact.lookup")))
    pool.add(ToolSpec("file.search", "search files by keyword", ["query", "limit"], benchSchema("file.search")))
    pool.add(ToolSpec("notice.send", "send a notification", ["text"], benchSchema("notice.send")))
    pool.add(ToolSpec("web.search", "search the web", ["query", "limit"], benchSchema("web.search")))
    return pool
}

@Test
@Bench
public func benchEstimateTokens(): Unit {
    let s = "search the web for the latest news about on-device multi-agent systems"
    for (i in 0..200) {
        estimateTokens(s)
    }
}

@Test
@Bench
public func benchEagerSchemas(): Unit {
    let pool = benchPool()
    for (i in 0..200) {
        pool.eagerSchemas()
    }
}

@Test
@Bench
public func benchStagedSchemas(): Unit {
    let pool = benchPool()
    for (i in 0..200) {
        pool.stagedSchemas("search my files for the quarterly report", 3)
    }
}

// ---------------------------------------------------------------------------
// Bottleneck isolation for the staged-injection path.
//
// `benchStagedSchemas` was measured ~22x slower than `benchEagerSchemas`.
// The first explanation offered (an O(n^2) insertion sort) does not survive
// arithmetic: with 5 tools the sort performs ~25 comparisons, which cannot
// explain a 22x gap. These benchmarks separate the candidates so the real
// hotspot is identified by measurement rather than by guesswork.
// ---------------------------------------------------------------------------

@Test
@Bench
public func benchSummaryPoolOnly(): Unit {
    let pool = benchPool()
    for (i in 0..200) {
        pool.summaryPool()
    }
}

@Test
@Bench
public func benchSelectTopKOnly(): Unit {
    let pool = benchPool()
    for (i in 0..200) {
        pool.selectTopK("search my files for the quarterly report", 3)
    }
}

@Test
@Bench
public func benchFullSchemaRenderOnly(): Unit {
    let pool = benchPool()
    for (i in 0..200) {
        pool.eagerSchemas()
    }
}

@Test
@Bench
public func benchSchedulerPlan(): Unit {
    let pool = benchPool()
    let net = NetState(NetTier.Wifi, 25, false, true)
    let ledger = Ledger(Budget(8000, 60000, 20, 50000))
    let s = BudgetScheduler(3)
    for (i in 0..200) {
        ledger.charge(7, 30, 0, 0)
        s.plan("search my files for the quarterly report", 0.5, pool, net, ledger)
    }
}
