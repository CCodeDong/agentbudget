#!/usr/bin/env python3
"""
校验"核心库"与"应用内副本"是否一致。

WHY THIS EXISTS
    `app/offlinelib/entry/src/main/ets/lib/` 是 `projects/offlinelib-core/src/`
    的手工复制。这是有意的——核心库要能脱离设备在 Node 里单测，
    而鸿蒙工程需要这些文件在 ets 目录下。

    **但手工复制会漂移。**

    这个项目已经因为"两份副本不一致"吃过一次亏：
    `_out` 里放着 251,360 B 的旧 HAP，而构建目录里是 184,284 B 的新包，
    导致一度分不清哪个才是当前产物。

    软著登记提交的是**当前这份代码**，如果它与实际构建的不是同一份，
    登记材料就失真了。所以这个检查要在提交前跑。

USAGE
    python tools/check_lib_sync.py           # 只检查
    python tools/check_lib_sync.py --sync    # 检查并把核心库覆盖到应用
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "projects" / "offlinelib-core" / "src"
APP_LIB = ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "ets" / "lib"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sync", action="store_true", help="把核心库覆盖到应用（核心库为准）")
    args = ap.parse_args()

    if not CORE.exists():
        print(f"[sync] 核心库不存在：{CORE}")
        return 2
    if not APP_LIB.exists():
        print(f"[sync] 应用内 lib 目录不存在：{APP_LIB}")
        return 2

    print("=" * 70)
    print("核心库 <=> 应用副本 一致性校验")
    print("=" * 70)
    print(f"  核心库 : {CORE.relative_to(ROOT)}")
    print(f"  应用   : {APP_LIB.relative_to(ROOT)}")
    print()

    core_files = {p.name: p for p in CORE.glob("*.ts")}
    lib_files = {p.name: p for p in APP_LIB.glob("*.ts")}

    ok = True
    synced = 0
    print(f"  {'文件':<16}{'状态':<12}{'核心库':<14}{'应用'}")
    print("  " + "-" * 50)

    for name in sorted(set(core_files) | set(lib_files)):
        a = core_files.get(name)
        b = lib_files.get(name)
        if a is None:
            print(f"  {name:<16}{'应用多出':<12}{'-':<14}{sha(b)[:10]}")
            ok = False
            continue
        if b is None:
            print(f"  {name:<16}{'应用缺失':<12}{sha(a)[:10]:<14}-")
            ok = False
            if args.sync:
                shutil.copy2(a, APP_LIB / name)
                synced += 1
            continue
        ha, hb = sha(a), sha(b)
        if ha == hb:
            print(f"  {name:<16}{'一致':<12}{ha[:10]:<14}{hb[:10]}")
        else:
            print(f"  {name:<16}{'不一致 !':<12}{ha[:10]:<14}{hb[:10]}")
            ok = False
            if args.sync:
                shutil.copy2(a, APP_LIB / name)
                synced += 1

    print()
    if args.sync and synced > 0:
        print(f"[sync] 已把 {synced} 个文件从核心库同步到应用（以核心库为准）")
        print("[sync] 请重新构建验证：python tools/deploy_offlinelib.py build")
        return 0

    if ok:
        print("[sync] 全部一致 —— 软著登记的代码就是实际构建的代码。")
        return 0
    else:
        print("[sync] 有差异！")
        print("       若核心库是最新的，运行：python tools/check_lib_sync.py --sync")
        print("       若改的是应用侧，请把改动搬回核心库（核心库才是可单测的那份）")
        return 1


if __name__ == "__main__":
    sys.exit(main())
