package probe

import std.unittest.*
import std.unittest.testmacro.*

public func buildString(): String {
    let sb = StringBuilder()
    sb.append("a")
    sb.append("b")
    return sb.toString()
}

@Test
public func testBuildString() {
    @Expect(buildString(), "ab")
}
