#!/usr/bin/env python3
"""
证明「离线资料库」代码里没有任何网络能力。

WHY THIS SCRIPT
    说"我们不联网"很容易，让人信不容易。口头声明是最弱的一层证据。

    这个脚本把"不联网"变成**可复核的检查**：扫全部源码，找网络相关的
    导入与调用；同时检查权限声明与依赖。任何人都能重跑。

    它服务于三件事：
      · APP 备案判定（单机不联网的应用无需备案）
      · 应用市场提审说明（零权限主张）
      · 答辩时的"数据不出设备"主张

输出分三段：
    ① 权限声明    —— module.json5 里申请了什么权限
    ② 代码扫描    —— 源码里有没有网络 API
    ③ 依赖检查    —— 有没有引入网络相关的第三方包

USAGE
    python tools/check_no_network.py
    python tools/check_no_network.py --json     # 机器可读输出
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETS = ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "ets"
MODULE_JSON = ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "module.json5"
OH_PACKAGE = ROOT / "app" / "offlinelib" / "entry" / "oh-package.json5"

# 网络能力的特征串。命中任意一条就要人工复查。
#
# 注意：这里刻意**不匹配中文"网络"二字** —— 我们自己的注释里大量提到"网络"，
# 那是在说明"不联网"，匹配它会制造大量假阳性。
NETWORK_PATTERNS = [
    # Kit 导入
    (r"@kit\.(NetworkKit|NetworkCoreKit|RemoteCommunicationKit)", "网络 Kit 导入"),
    (r"@ohos\.net\.\w+", "@ohos.net 模块导入"),
    (r"@ohos\.(http|socket|webSocket)\b", "网络模块导入"),
    # 接口调用
    (r"\bhttp\.createHttp\b", "HTTP 客户端"),
    (r"\bHttpRequest\b", "HTTP 请求对象"),
    (r"\bsocket\.construct\w+", "Socket 构造"),
    (r"\bcreateWebSocket\b", "WebSocket"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
    (r"\bfetch\s*\(", "fetch 调用"),
    (r"\brequest\s*\(\s*url", "请求调用"),
    (r"\bdownloadFile\b", "文件下载"),
    (r"\buploadFile\b", "文件上传"),
    (r"\bconnection\.\w+", "网络连接管理"),
    # 网络状态
    (r"GET_NETWORK_INFO", "网络状态权限"),
    (r"\bgetNetCapabilities\b", "网络能力查询"),
]

# 权限名里出现这些词就认为涉及网络
NETWORK_PERMISSION_HINTS = ["INTERNET", "NETWORK", "WIFI", "BLUETOOTH", "NFC"]


def scan_permissions() -> dict:
    """读取 module.json5 的权限声明。"""
    result = {"file": str(MODULE_JSON.relative_to(ROOT)), "exists": MODULE_JSON.exists(),
              "requestPermissions": [], "network_permissions": []}
    if not MODULE_JSON.exists():
        return result
    text = MODULE_JSON.read_text(encoding="utf-8")
    # 抓 requestPermissions 数组里的权限名
    m = re.search(r'"requestPermissions"\s*:\s*\[(.*?)\]', text, re.S)
    if not m:
        result["requestPermissions"] = []
        return result
    body = m.group(1)
    perms = re.findall(r'"name"\s*:\s*"([^"]+)"', body)
    result["requestPermissions"] = perms
    for p in perms:
        upper = p.upper()
        if any(h in upper for h in NETWORK_PERMISSION_HINTS):
            result["network_permissions"].append(p)
    return result


def scan_code() -> dict:
    """扫描全部源码里的网络特征串。"""
    hits = []
    files = 0
    lines = 0
    for p in sorted(ETS.rglob("*")):
        if p.suffix not in (".ts", ".ets"):
            continue
        files += 1
        content = p.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            # 跳过纯注释行：注释里讨论"网络"是正常的
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            for pattern, label in NETWORK_PATTERNS:
                if re.search(pattern, line):
                    hits.append({
                        "file": str(p.relative_to(ETS)),
                        "line": lineno,
                        "label": label,
                        "code": stripped[:120],
                    })
                    break
        lines += len(content.splitlines())
    return {"files": files, "lines": lines, "hits": hits}


def scan_deps() -> dict:
    """检查依赖里有没有网络相关的包。"""
    result = {"file": str(OH_PACKAGE.relative_to(ROOT)), "exists": OH_PACKAGE.exists(),
              "dependencies": {}, "suspicious": []}
    if not OH_PACKAGE.exists():
        return result
    text = OH_PACKAGE.read_text(encoding="utf-8")
    for key in ("dependencies", "devDependencies"):
        m = re.search(rf'"{key}"\s*:\s*\{{(.*?)\}}', text, re.S)
        if not m:
            continue
        names = re.findall(r'"([^"]+)"\s*:', m.group(1))
        result["dependencies"][key] = names
        for n in names:
            low = n.lower()
            if any(h in low for h in ("http", "request", "axios", "network", "socket", "net")):
                result["suspicious"].append(n)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    perms = scan_permissions()
    code = scan_code()
    deps = scan_deps()

    ok = (not perms["network_permissions"]) and (not code["hits"]) and (not deps["suspicious"])

    if args.json:
        print(json.dumps({"ok": ok, "permissions": perms, "code": code, "deps": deps},
                         ensure_ascii=False, indent=2))
        return 0 if ok else 1

    print("=" * 72)
    print("「离线资料库」零网络能力核查")
    print("=" * 72)
    print()

    # ① 权限
    print("① 权限声明")
    print(f"   文件：{perms['file']}")
    if perms["requestPermissions"]:
        print(f"   申请权限：{perms['requestPermissions']}")
    else:
        print("   申请权限：[] —— 一个都没有")
    if perms["network_permissions"]:
        print(f"   [X] 含网络相关权限：{perms['network_permissions']}")
    else:
        print("   [OK] 无任何网络相关权限")
    print()

    # ② 代码
    print("② 代码扫描")
    print(f"   范围：{code['files']} 个文件 / {code['lines']} 行")
    if code["hits"]:
        print(f"   [X] 命中 {len(code['hits'])} 处网络特征：")
        for h in code["hits"]:
            print(f"       {h['file']}:{h['line']}  {h['label']}")
            print(f"         {h['code']}")
    else:
        print("   [OK] 未发现任何网络 API 调用或网络模块导入")
    print()

    # ③ 依赖
    print("③ 依赖检查")
    print(f"   文件：{deps['file']}")
    total = sum(len(v) for v in deps["dependencies"].values())
    print(f"   依赖总数：{total}")
    if deps["suspicious"]:
        print(f"   [X] 可疑网络相关依赖：{deps['suspicious']}")
    else:
        print("   [OK] 无网络相关第三方依赖")
    print()

    print("=" * 72)
    if ok:
        print("结论：三层全部通过 —— 应用不具备网络能力。")
        print("      属于「单机不联网的 APP」，无需办理 APP 备案。")
        print("      依据见 docs/APP备案判定-免备案依据.md")
    else:
        print("结论：发现网络痕迹，需要人工复查上面标记的项。")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
