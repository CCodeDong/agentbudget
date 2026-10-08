// std-only (no stdx) minimal HTTP/1.1 client -- VERIFIED working with cjc 1.0.5 on Windows x64.
// Requires the project directory to be an ASCII-only path.
package minihttp

import std.net.*
import std.collection.*

func httpGet(host: String, port: UInt16, path: String): String {
    let sb = StringBuilder()
    try (socket = TcpSocket(host, port)) {
        socket.connect()
        let req = "GET ${path} HTTP/1.1\r\nHost: ${host}\r\nUser-Agent: cangjie-std/1.0.5\r\nAccept: */*\r\nConnection: close\r\n\r\n"
        socket.write(req.toArray())
        let buf = Array<Byte>(4096, repeat: 0)
        let all = ArrayList<Byte>()
        var n = socket.read(buf)
        while (n > 0) {
            for (i in 0..n) {
                all.add(buf[i])
            }
            n = socket.read(buf)
        }
        sb.append(String.fromUtf8(all.toArray()))
    }
    return sb.toString()
}

main(): Int64 {
    let resp = httpGet("example.com", 80, "/")
    let head = if (resp.size > 400) { resp[..400] } else { resp }
    println(head)
    println("=== total length: ${resp.size} ===")
    return 0
}
