#!/usr/bin/env python3
"""
真机连接与诊断工具。

WHY THIS EXISTS
    真机调试涉及一串容易记错的步骤：hdc 路径、无线连接、设备信息、安装、启动、日志。
    把它们固化成一条命令，既省事，也让"设备到底连上没有、装了哪个版本"这类问题
    有确定的答案，而不是靠回忆。

USAGE
    python tools/device.py probe                     # 只探测：设备列表 + 网络环境
    python tools/device.py connect 192.168.1.5:10178 # 无线连接
    python tools/device.py discover                  # 局域网广播发现（需放行 UDP 8710）
    python tools/device.py info                      # 设备型号 / 版本 / API
    python tools/device.py install                   # 安装最新 HAP
    python tools/device.py launch                    # 启动应用
    python tools/device.py log                       # 抓取应用日志
    python tools/device.py firewall                  # 打印放行 UDP 8710 的命令（需管理员）
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HDC = Path(r"D:\develop\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe")
HAPDIR = ROOT / "app" / "harmony" / "_out"
APPDIR = ROOT / "app" / "harmony"
BUNDLE = "com.xjtu.agentbudget"


def hap():
    """优先返回**已签名**的包——unsigned 的装不上。

    signingConfigs 配好后，hvigor 会同时产出 signed 与 unsigned 两个文件。
    按名字挑，可以避免"默认拿 unsigned 去装、然后报一个令人困惑的签名错误"。
    """
    signed = HAPDIR / "entry-default-signed.hap"
    if signed.exists():
        return signed
    unsigned = HAPDIR / "entry-default-unsigned.hap"
    if unsigned.exists():
        return unsigned
    return None


def hdc(*args, timeout=60):
    """运行 hdc，返回 (exit_code, stdout+stderr)。"""
    if not HDC.exists():
        return 127, f"hdc not found: {HDC}"
    try:
        r = subprocess.run([str(HDC), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: hdc {' '.join(args)}"


def local_ips():
    """本机 IPv4。用 ipconfig 解析，避免依赖 netifaces 之类的额外包。"""
    try:
        r = subprocess.run(["ipconfig"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out, cur, res = r.stdout, "", []
        for line in out.splitlines():
            if "adapter" in line.lower():
                cur = line.strip().rstrip(":")
            if "IPv4" in line:
                ip = line.split(":")[-1].strip()
                if ip and not ip.startswith("127."):
                    res.append((ip, cur))
        return res
    except Exception:
        return []


def cmd_probe():
    print("=" * 70)
    print("HDC 环境探测")
    print("=" * 70)
    print(f"  hdc 路径   : {HDC}  {'[存在]' if HDC.exists() else '[缺失]'}")
    if HDC.exists():
        _, v = hdc("version")
        print(f"  hdc 版本   : {v.strip().splitlines()[0] if v.strip() else '?'}")
        _, cs = hdc("checkserver")
        print(f"  服务端     : {cs.strip()}")

    print()
    print("  本机 IPv4：")
    ips = local_ips()
    for ip, name in ips or [("(未取得)", "")]:
        print(f"    {ip:<16} {name}")
    hotspot = any(ip.startswith("172.20.10.") for ip, _ in ips)
    if hotspot:
        print("    [注意] 172.20.10.x 是手机热点网段——"
              "MateBook 必须连同一个热点，否则无法互通")

    print()
    print("  已连接设备：")
    _, t = hdc("list targets")
    t = t.strip()
    if not t or t == "[Empty]":
        print("    [Empty] —— 无线调试尚未连接")
        print("    下一步：在 MateBook 打开「无线调试」，记下 IP:端口，然后")
        print("            python tools/device.py connect <IP>:<端口>")
    else:
        for line in t.splitlines():
            print(f"    {line.strip()}")
    return 0


def cmd_connect(key):
    if ":" not in key:
        print(f"[device] 需要 ip:port 形式，收到：{key}")
        return 2
    print(f"[device] hdc tconn {key}")
    code, out = hdc("tconn", key, timeout=30)
    print("  " + (out.strip() or f"(exit {code})"))
    print()
    _, t = hdc("list targets")
    ok = t.strip() and t.strip() != "[Empty]"
    print(f"[device] list targets -> {t.strip()}")
    print("[device] 连接成功。" if ok else "[device] 仍未连上，检查：同一网段 / 设备端授权弹窗 / 端口号")
    return 0 if ok else 1


def cmd_discover():
    print("[device] hdc discover（LAN 广播，需要 UDP 8710 入站放行）")
    code, out = hdc("discover", timeout=30)
    print("  " + out.strip().replace("\n", "\n  "))
    if "firewall" in out.lower():
        print()
        print("  [提示] 先放行防火墙：python tools/device.py firewall")
    return 0


def cmd_firewall():
    print("[device] 放行 hdc 广播发现的 UDP 8710 入站。")
    print("          需要**管理员权限**的 PowerShell，命令如下：")
    print()
    print('  New-NetFirewallRule -DisplayName "HDC discover UDP 8710" '
          '-Direction Inbound -Protocol UDP -LocalPort 8710 -Action Allow')
    print()
    print("  放行后重试：python tools/device.py discover")
    print("  （若不想改防火墙，直接用设备上显示的 IP:端口 走 connect 即可）")
    return 0


def cmd_info():
    cmds = [
        ("型号", ["shell", "param", "get", "const.product.model"]),
        ("系统版本", ["shell", "param", "get", "const.product.software.version"]),
        ("API 版本", ["shell", "param", "get", "const.ohos.apiversion"]),
        ("设备类型", ["shell", "param", "get", "const.product.devicetype"]),
    ]
    print("=" * 70)
    print("设备信息")
    print("=" * 70)
    for label, args in cmds:
        code, out = hdc(*args, timeout=20)
        val = out.strip() or f"(exit {code})"
        print(f"  {label:<10}: {val}")
    print()
    print("  [关注点] 设备类型若为 2in1，则该设备**具备** AI.CANN.LLMEngine，")
    print("           不属于论文的目标形态（手机）——报告里需如实标注。")
    return 0


def cmd_install():
    h = hap()
    if h is None:
        print(f"[device] 未找到 HAP（查找目录：{HAPDIR}）")
        print("          先构建：powershell -ExecutionPolicy Bypass -File tools\\hb.ps1 assembleHap")
        return 2
    if "unsigned" in h.name:
        print("[device] 警告：只找到 unsigned 的包，很可能装不上。")
        print("          DevEco -> File -> Project Structure -> Signing Configs 开启自动签名后重新构建。")
    print(f"[device] 安装 {h.name}（{h.stat().st_size:,} B）")
    code, out = hdc("install", "-r", str(h), timeout=300)
    print("  " + out.strip().replace("\n", "\n  "))
    low = out.lower()
    if "success" in low:
        print("[device] 安装成功。")
    elif "sign" in low:
        print("[device] 签名相关失败：确认 signingConfigs 已配置、证书未过期。")
    return 0 if code == 0 else 1


def cmd_launch():
    code, out = hdc("shell", "aa", "start", "-b", BUNDLE, "-a", "EntryAbility", timeout=60)
    print("  " + out.strip().replace("\n", "\n  "))
    if code != 0:
        print(f"  [提示] 启动失败。可先确认已安装：hdc shell bm dump -a | findstr {BUNDLE}")
    return 0


def cmd_log():
    print("[device] 抓取应用日志（Ctrl+C 停止）。关注 hilog 中与 A2A / BudgetPolicy 相关的行。")
    try:
        subprocess.run([str(HDC), "hilog"], timeout=None)
    except KeyboardInterrupt:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("probe")
    p = sub.add_parser("connect"); p.add_argument("key")
    sub.add_parser("discover")
    sub.add_parser("firewall")
    sub.add_parser("info")
    sub.add_parser("install")
    sub.add_parser("launch")
    sub.add_parser("log")
    args = ap.parse_args()

    return {
        "probe": cmd_probe,
        "connect": lambda: cmd_connect(args.key),
        "discover": cmd_discover,
        "firewall": cmd_firewall,
        "info": cmd_info,
        "install": cmd_install,
        "launch": cmd_launch,
        "log": cmd_log,
    }.get(args.cmd, cmd_probe)()


if __name__ == "__main__":
    sys.exit(main())
