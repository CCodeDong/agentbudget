package minijson

import std.collection.*
import std.convert.*

enum JVal {
    | JNull
    | JBool(Bool)
    | JNum(Float64, String)
    | JStr(String)
    | JArr(ArrayList<JVal>)
    | JObj(HashMap<String, JVal>)
}

class Parser {
    let b: Array<Byte>
    var i: Int64 = 0

    init(text: String) {
        b = text.toArray()
    }

    func peek(): Int64 {
        if (i >= b.size) {
            return -1
        }
        return Int64(b[i])
    }

    func skipWs(): Unit {
        while (i < b.size) {
            let c = b[i]
            if (c == 0x20 || c == 0x09 || c == 0x0A || c == 0x0D) {
                i++
            } else {
                break
            }
        }
    }

    func expect(ch: Byte): Unit {
        skipWs()
        if (i >= b.size || b[i] != ch) {
            throw IllegalArgumentException("JSON: expect '${ch}' at ${i}")
        }
        i++
    }

    func parseString(): String {
        expect(0x22)
        let acc = ArrayList<Byte>()
        while (i < b.size && b[i] != 0x22) {
            if (b[i] == 0x5C) {
                i++
                if (i >= b.size) { break }
                let e = b[i]
                if (e == 0x6E) { acc.add(0x0A) }
                else if (e == 0x74) { acc.add(0x09) }
                else if (e == 0x72) { acc.add(0x0D) }
                else if (e == 0x62) { acc.add(0x08) }
                else if (e == 0x66) { acc.add(0x0C) }
                else if (e == 0x2F) { acc.add(0x2F) }
                else if (e == 0x22) { acc.add(0x22) }
                else if (e == 0x5C) { acc.add(0x5C) }
                else if (e == 0x75) {
                    // \uXXXX : copy the 4 hex digits verbatim (simple ASCII case)
                    i++
                    for (k in 0..4) {
                        if (i < b.size) { acc.add(b[i]); i++ }
                    }
                    continue
                } else { acc.add(e) }
                i++
            } else {
                acc.add(b[i])
                i++
            }
        }
        expect(0x22)
        return String.fromUtf8(acc.toArray())
    }

    func parseNumber(): JVal {
        skipWs()
        let start = i
        while (i < b.size) {
            let c = b[i]
            if ((c >= 0x30 && c <= 0x39) || c == 0x2D || c == 0x2B || c == 0x2E || c == 0x65 || c == 0x45) {
                i++
            } else {
                break
            }
        }
        let raw = String.fromUtf8(b[start..i])
        return JNum(Float64.parse(raw), raw)
    }

    func parseArray(): JVal {
        expect(0x5B)
        let arr = ArrayList<JVal>()
        skipWs()
        if (peek() == 0x5D) {
            i++
            return JArr(arr)
        }
        while (true) {
            arr.add(parseValue())
            skipWs()
            if (peek() == 0x2C) {
                i++
            } else {
                break
            }
        }
        expect(0x5D)
        return JArr(arr)
    }

    func parseObject(): JVal {
        expect(0x7B)
        let m = HashMap<String, JVal>()
        skipWs()
        if (peek() == 0x7D) {
            i++
            return JObj(m)
        }
        while (true) {
            skipWs()
            let k = parseString()
            expect(0x3A)
            m[k] = parseValue()
            skipWs()
            if (peek() == 0x2C) {
                i++
            } else {
                break
            }
        }
        expect(0x7D)
        return JObj(m)
    }

    func parseValue(): JVal {
        skipWs()
        let c = peek()
        if (c == 0x7B) { return parseObject() }
        if (c == 0x5B) { return parseArray() }
        if (c == 0x22) { return JStr(parseString()) }
        if (c == 0x74) { i += 4; return JBool(true) }
        if (c == 0x66) { i += 5; return JBool(false) }
        if (c == 0x6E) { i += 4; return JNull }
        return parseNumber()
    }
}

func parse(text: String): JVal {
    let p = Parser(text)
    let v = p.parseValue()
    p.skipWs()
    if (p.i != p.b.size) {
        throw IllegalArgumentException("JSON: trailing data at ${p.i}")
    }
    return v
}

func enc(s: String): String {
    let out = StringBuilder()
    out.append("\"")
    for (r in s.toRuneArray()) {
        if (r == r'"') { out.append("\\\"") }
        else if (r == r'\\') { out.append("\\\\") }
        else if (r == r'\n') { out.append("\\n") }
        else if (r == r'\t') { out.append("\\t") }
        else if (r == r'\r') { out.append("\\r") }
        else { out.append(r) }
    }
    out.append("\"")
    return out.toString()
}

func dump(v: JVal): String {
    match (v) {
        case JNull => return "null"
        case JBool(b) => return if (b) { "true" } else { "false" }
        case JNum(n, raw) =>
            return raw
        case JStr(s) => return enc(s)
        case JArr(a) =>
            let parts = ArrayList<String>()
            for (x in a) { parts.add(dump(x)) }
            return "[" + String.join(parts.toArray(), delimiter: ",") + "]"
        case JObj(m) =>
            let parts = ArrayList<String>()
            for ((k, x) in m) { parts.add(enc(k) + ":" + dump(x)) }
            return "{" + String.join(parts.toArray(), delimiter: ",") + "}"
    }
}

func getStr(m: HashMap<String, JVal>, k: String): String {
    return match (m.get(k)) {
        case Some(JStr(s)) => s
        case _ => "<missing>"
    }
}

func getNum(m: HashMap<String, JVal>, k: String): String {
    return match (m.get(k)) {
        case Some(JNum(n, _)) => n.toString()
        case _ => "<missing>"
    }
}

func getLen(m: HashMap<String, JVal>, k: String): String {
    return match (m.get(k)) {
        case Some(JArr(a)) => a.size.toString()
        case _ => "<missing>"
    }
}

main(): Int64 {
    let text = ##"{"name":"cangjie","ver":1.05,"ok":true,"nil":null,"tags":["a","b"],"nested":{"k":[1,2,3]}}"##
    let v = parse(text)
    println("round-trip: " + dump(v))

    match (v) {
        case JObj(m) =>
            println("name      = " + getStr(m, "name"))
            println("ver       = " + getNum(m, "ver"))
            println("tags.size = " + getLen(m, "tags"))
        case _ => println("not an object")
    }
    return 0
}
