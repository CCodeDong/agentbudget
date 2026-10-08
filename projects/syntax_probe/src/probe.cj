package probe

import std.collection.*
import std.unittest.*
import std.unittest.testmacro.*

public enum MsgKind {
    | Natural
    | Summary
    | Structured
}

public enum AgentMsg {
    | Text(String)
    | Compact(Int64, String)
}

public interface Policy {
    func decide(budget: Int64, cost: Int64): Bool
}

public class ThresholdPolicy <: Policy {
    let limit: Int64

    public init(limit: Int64) {
        this.limit = limit
    }

    public func decide(budget: Int64, cost: Int64): Bool {
        cost <= limit
    }
}

public struct Budget {
    public let tokens: Int64
    public let latencyMs: Int64

    public init(tokens: Int64, latencyMs: Int64) {
        this.tokens = tokens
        this.latencyMs = latencyMs
    }
}

public func render(m: AgentMsg): String {
    match (m) {
        case Text(s) => s
        case Compact(n, s) => "${n}:${s}"
    }
}

public func sumParallel(n: Int64): Int64 {
    let futures = ArrayList<Future<Int64>>()
    for (i in 0..n) {
        futures.add(spawn { => i * 2 })
    }
    var total = 0
    for (f in futures) {
        total += f.get()
    }
    return total
}

@Test
public func testRender() {
    @Expect(render(Text("hi")), "hi")
    @Expect(sumParallel(4), 12)
}
