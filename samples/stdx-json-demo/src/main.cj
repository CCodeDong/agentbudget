// Minimal stdx smoke test -- VERIFIED working with cjc 1.0.5 + stdx 1.0.5.1 on Windows x64.
// Project directory MUST be an ASCII-only path (see the manual, section 7).
package stdxjson

import stdx.encoding.json.*

main(): Int64 {
    let str = ##"{"name":"cangjie","version":105,"tags":["stdx","json"],"ok":true}"##
    let jv: JsonValue = JsonValue.fromStr(str)
    println("toString     = ${jv.toString()}")
    println("toJsonString =")
    println(jv.toJsonString())
    return 0
}
