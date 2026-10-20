#!/usr/bin/env python3
"""
离线资料库核心（offlinelib-core）的构建与测试入口。

WHY THIS SCRIPT
    这个工程刻意**零 npm 依赖** —— 不装 jest、不装 @types/node。
    但它需要一个 TypeScript 编译器，而当前环境没有全局 tsc。
    所以这个脚本负责**找到 DevEco Studio 自带的 tsc** 并调用它。

    这样别人克隆仓库后**只需要装 Node（>=22）**，不需要 npm install，
    一条命令就能复现全部测试。这直接对应老师那条批评——
    "检索技术路线无法核实"的解法是**别人能一条命令跑出来**。

USAGE
    python tools/olib.py test        # 编译 + 跑全部单元测试
    python tools/olib.py build       # 只编译
    python tools/olib.py clean       # 清掉 dist/
    python tools/olib.py dev         # 编译并跑测试，失败时以非零码退出
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "projects" / "offlinelib-core"
DIST = CORE / "dist"

# 按优先级找 tsc：项目内 → DevEco 的几处 → PATH
TSC_CANDIDATES = [
    CORE / "node_modules" / "typescript" / "bin" / "tsc",
    Path(r"D:\develop\DevEco Studio\tools\hvigor\hvigor-ohos-plugin\node_modules\typescript\bin\tsc"),
    Path(r"D:\develop\DevEco Studio\tools\hvigor\hvigor\node_modules\typescript\bin\tsc"),
    Path(r"D:\develop\DevEco Studio\tools\arktsdoc\node_modules\typescript\bin\tsc"),
]


def find_tsc() -> Path | None:
    for p in TSC_CANDIDATES:
        if p.exists():
            return p
    which = shutil.which("tsc")
    return Path(which) if which else None


def run_node(args, cwd):
    """跑 node 并**继承 stdio**。

    注意不要用 capture_output：当前沙箱禁止管道通信，
    `subprocess.run(..., capture_output=True)` 会以 EPERM 失败。
    继承 stdio 既规避了限制，也让测试输出直接可见。
    """
    return subprocess.run(["node", *args], cwd=str(cwd)).returncode


def build() -> int:
    tsc = find_tsc()
    if tsc is None:
        print("[olib] 找不到 TypeScript 编译器。")
        print("         可以装全局 tsc (npm i -g typescript)，")
        print("         或确认 DevEco Studio 装在 D:\\develop\\DevEco Studio。")
        return 2
    print(f"[olib] tsc = {tsc}")
    code = run_node([str(tsc), "-p", str(CORE / "tsconfig.json")], CORE)
    print(f"[olib] 编译退出码 = {code}")
    return code


def test() -> int:
    code = build()
    if code != 0:
        return code
    test_dir = DIST / "test"
    if not test_dir.exists():
        print(f"[olib] 找不到测试目录：{test_dir}")
        return 2
    # 逐个跑，而不是用 `node --test`：--test 会为每个文件 spawn 子进程，
    # 而当前沙箱禁止管道通信，会以 EPERM 失败。
    files = sorted(test_dir.glob("*.test.js"))
    if not files:
        print(f"[olib] {test_dir} 下没有 *.test.js")
        return 2
    worst = 0
    for f in files:
        print(f"[olib] 运行 {f.name}")
        rc = run_node([str(f)], CORE)
        if rc != 0:
            worst = rc
    print(f"[olib] 共 {len(files)} 个测试文件，{'全部通过' if worst == 0 else '有失败'}")
    return worst


def clean() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
        print(f"[olib] 已删除 {DIST}")
    else:
        print("[olib] dist/ 不存在，无需清理")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="test",
                    choices=["test", "build", "clean", "dev"])
    args = ap.parse_args()

    if not CORE.exists():
        print(f"[olib] 工程不存在：{CORE}")
        return 2

    return {"test": test, "dev": test, "build": build, "clean": clean}[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
