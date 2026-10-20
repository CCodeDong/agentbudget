#!/usr/bin/env python3
"""
离线资料库：构建 → 安装 → 启动 → 截图（一条命令完成 L3 验证）。

WHY THIS SCRIPT
    L3 验证（设备内自测）要手动做四件事：构建、连设备、装、启动、截图。
    每一步都有参数要记，而且设备掉线后要重来。

    这个脚本把它们串起来，并在每一步失败时给出**可操作的提示**，
    而不是抛一个看不懂的错误。

前置条件
    1. 模拟器或真机已连接（`hdc list targets` 非空）
    2. 已配置发布签名（见 docs/AGC签名申请指南.md）
       —— 或者临时用旧包名跑验证

USAGE
    python tools/deploy_offlinelib.py check      # 只检查前置条件
    python tools/deploy_offlinelib.py build      # 只构建
    python tools/deploy_offlinelib.py deploy     # 构建 + 安装 + 启动 + 截图
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "offlinelib"
DEV = Path(r"D:\develop\DevEco Studio")
HDC = DEV / "sdk" / "default" / "openharmony" / "toolchains" / "hdc.exe"
BUNDLE = "com.xjtu.offlinelib"
OUT = APP / "_out"
SHOTS = OUT / "screenshots"


def run(cmd, cwd=None, timeout=900, capture=False):
    """跑命令。

    capture=False 时继承 stdio —— 这在当前沙箱里是必须的：
    用管道捕获子进程输出会以 EPERM 失败。
    """
    kw = {"cwd": str(cwd) if cwd else None, "timeout": timeout}
    if capture:
        kw["capture_output"] = True
        kw["text"] = True
        kw["encoding"] = "utf-8"
        kw["errors"] = "replace"
    return subprocess.run(cmd, **kw)


def hdc(*args, timeout=120, capture=True):
    if not HDC.exists():
        return 127, f"hdc 不存在：{HDC}"
    r = run([str(HDC), *args], timeout=timeout, capture=capture)
    if capture:
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    return r.returncode, ""


def hap_path():
    """找最新的 signed HAP。"""
    d = APP / "entry" / "build" / "default" / "outputs" / "default"
    if not d.exists():
        return None
    signed = sorted(d.glob("*signed.hap"), key=lambda p: p.stat().st_mtime, reverse=True)
    if signed:
        return signed[0]
    unsigned = sorted(d.glob("*unsigned.hap"), key=lambda p: p.stat().st_mtime, reverse=True)
    return unsigned[0] if unsigned else None


def check():
    print("=" * 70)
    print("前置条件检查")
    print("=" * 70)
    ok = True

    print(f"  工程目录     : {APP}  {'[有]' if APP.exists() else '[缺]'}")
    if not APP.exists():
        ok = False

    print(f"  hdc          : {'[有]' if HDC.exists() else '[缺]'}")
    if not HDC.exists():
        ok = False

    # 设备
    _, out = hdc("list targets")
    targets = [t for t in out.splitlines() if t.strip() and "[Empty]" not in t]
    if targets:
        print(f"  已连接设备   : {', '.join(targets)}")
    else:
        print("  已连接设备   : [None] —— 需要先启动模拟器或在 DevEco 里连接真机")
        ok = False

    # 签名配置
    bp = APP / "build-profile.json5"
    if bp.exists():
        txt = bp.read_text(encoding="utf-8", errors="replace")
        if '"signingConfigs": []' in txt:
            print("  签名配置     : [空] —— 需要配置发布签名（见 docs/AGC签名申请指南.md）")
            ok = False
        else:
            alias = "debugKey" if "debugKey" in txt else "（发布证书）"
            print(f"  签名配置     : [已配置] keyAlias = {alias}")
            if "debugKey" in txt:
                print("        [!] 这是调试证书，能装到设备但**不能上架**")

    # 包名一致性
    appjson = APP / "AppScope" / "app.json5"
    if appjson.exists():
        t = appjson.read_text(encoding="utf-8", errors="replace")
        has = f'"{BUNDLE}"' in t
        print(f"  包名         : {BUNDLE}  {'[一致]' if has else '[不一致！]'}")
        if not has:
            ok = False

    print()
    print("  结论：" + ("前置条件满足，可以 deploy" if ok else "有前置条件未满足，见上方 [!]"))
    return 0 if ok else 1


def build():
    print("=" * 70)
    print("构建 offlinelib")
    print("=" * 70)
    hh = APP / "_hvhome"
    nc = APP / "_npmcache"
    hh.mkdir(parents=True, exist_ok=True)
    nc.mkdir(parents=True, exist_ok=True)
    (hh / ".npmrc").write_text("node-linker=hoisted", encoding="ascii")

    env_note = (
        "注意：hvigor 需要能创建符号链接，受限环境里需要提权。\n"
        "      如果构建失败且报 EPERM: symlink，就是这个原因。"
    )
    print(f"  {env_note}\n")

    # 用 cmd 包装以便设置环境变量
    cmd = (
        f'set "DEVECO_SDK_HOME={DEV / "sdk"}" && '
        f'set "HVIGOR_USER_HOME={hh}" && '
        f'set "npm_config_cache={nc}" && '
        f'set "npm_config_registry=https://registry.npmmirror.com" && '
        f'set "PATH={DEV / "tools" / "node"};{DEV / "tools" / "ohpm" / "bin"};'
        f'{DEV / "tools" / "hvigor" / "bin"};%PATH%" && '
        f'hvigorw.bat assembleHap --no-daemon'
    )
    rc = run(["cmd", "/c", cmd], cwd=APP).returncode
    print(f"\n  构建退出码 = {rc}")

    h = hap_path()
    if h:
        OUT.mkdir(parents=True, exist_ok=True)
        print(f"  产物: {h.name}  {h.stat().st_size:,} B")
    return rc


def deploy():
    print("=" * 70)
    print("L3 设备内验证：构建 → 安装 → 启动 → 截图")
    print("=" * 70)

    if check() != 0:
        print("\n  前置条件不满足，中止。")
        return 1

    rc = build()
    if rc != 0:
        # 签名失败但编译通过是常见情形——说明代码没问题，只是证书没配
        h = hap_path()
        if h and "unsigned" in h.name:
            print("\n  [!] 只产出了 unsigned 包：编译通过，但签名未配置。")
            print("     装上不去。需要 AGC 发布签名，见 docs/AGC签名申请指南.md")
        return rc

    h = hap_path()
    if h is None:
        print("  找不到 HAP 产物")
        return 2
    if "unsigned" in h.name:
        print(f"  [!] 产物是 unsigned 包（{h.name}），无法安装。")
        print("     需要先配置发布签名。")
        return 2

    print(f"\n  安装 {h.name}")
    rc, out = hdc("install", "-r", str(h), timeout=300)
    print("  " + out.strip().replace("\n", "\n  "))
    if "success" not in out.lower():
        print("  安装失败。若是签名问题，检查 signingConfigs 与包名是否匹配。")
        return 1

    print(f"\n  启动 {BUNDLE}")
    rc, out = hdc("shell", "aa", "start", "-b", BUNDLE, "-a", "EntryAbility")
    print("  " + out.strip())
    time.sleep(6)

    # 确认进程存活（判断是否加载期崩溃）
    _, ps = hdc("shell", f"ps -ef | grep {BUNDLE}")
    if BUNDLE in ps:
        print("  [OK] 进程存活")
    else:
        print("  [XX] 进程不在 —— 可能加载期崩溃。取崩溃日志：")
        print("     hdc shell ls -t /data/log/faultlog/faultlogger/ | head -1")
        print("     hdc file recv /data/log/faultlog/faultlogger/<该文件> .")
        return 1

    print("\n  截图")
    SHOTS.mkdir(parents=True, exist_ok=True)
    remote = "/data/local/tmp/offlinelib.jpeg"
    hdc("shell", f"snapshot_display -f {remote}")
    time.sleep(1)
    stamp = time.strftime("%H%M%S")
    local = SHOTS / f"L3-自测-{stamp}.jpeg"
    rc, out = hdc("file", "recv", remote, str(SHOTS / "L3-latest.jpeg"))
    print("  " + out.strip())
    latest = SHOTS / "L3-latest.jpeg"
    if latest.exists():
        print(f"  [OK] 截图已保存：{latest}")
        print("     这一步的截图就是 L3 验证的证据。")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="check",
                    choices=["check", "build", "deploy"])
    args = ap.parse_args()
    return {"check": check, "build": build, "deploy": deploy}[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
