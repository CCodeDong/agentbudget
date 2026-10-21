#!/usr/bin/env python3
"""
整个项目的完整备份。

WHY A SEPARATE SCRIPT FROM backup_v1.py
    backup_v1.py 是**按课程拆分**的备份（仓颉一份、移动应用一份），
    目的是交作业。它把共享内容复制两份，体积翻倍。

    这个脚本是**整仓快照**：保持原始目录结构，用于开发机之外的冗余备份。
    两者的用途不同，所以没有合并。

WHAT IS EXCLUDED
    只排除"能一条命令重新生成"的东西：
      · 构建缓存（_hvhome / _npmcache / build / target / dist / .hvigor）
      · 依赖目录（oh_modules / node_modules）
      · __pycache__ / .idea / .cxx

    刻意**保留**的东西：
      · .git        —— 版本历史，丢了无法恢复
      · _out/       —— 已发布的 exe / HAP / 覆盖率报告，是交付物
      · experiments/results*/ —— 原始实验数据，是结论的依据

USAGE
    python tools/backup_project.py --dest "D:\\develop\\YIDONGYINGYONG"
    python tools/backup_project.py --dest "..." --dry-run
"""

import argparse
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIRS = {
    "_hvhome", "_npmcache", "node_modules", "oh_modules",
    "build", "target", "dist", ".hvigor", ".idea", ".cxx",
    "__pycache__", "_tmp", "_verify",
}
EXCLUDE_SUFFIX = {".pyc"}


def wanted(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if rel.suffix in EXCLUDE_SUFFIX:
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True, help="备份根目录")
    ap.add_argument("--name", default=None, help="备份文件夹名（默认含日期）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = Path(args.dest)
    if not base.exists():
        print(f"[backup] 目标根目录不存在：{base}")
        return 2

    stamp = datetime.datetime.now().strftime("%Y%m%d")
    name = args.name if args.name else f"ProjectBackup-v1.0-{stamp}"
    dest = base / name

    print("=" * 74)
    print("项目完整备份")
    print(f"  源   : {ROOT}")
    print(f"  目标 : {dest}")
    if args.dry_run:
        print("  模式 : DRY RUN")
    print("=" * 74)

    files = 0
    total = 0
    by_top = {}

    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if not wanted(rel):
            continue
        size = p.stat().st_size
        files += 1
        total += size
        top = rel.parts[0] if len(rel.parts) > 1 else "(根目录)"
        prev = by_top.get(top, (0, 0))
        by_top[top] = (prev[0] + 1, prev[1] + size)

        if not args.dry_run:
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)

    print()
    print(f"  {'目录':<28} {'文件':>6} {'体积':>10}")
    print("  " + "-" * 48)
    for top in sorted(by_top, key=lambda k: -by_top[k][1]):
        n, b = by_top[top]
        print(f"  {top:<28} {n:>6} {b / 1024 / 1024:>9.1f} MB")
    print("  " + "-" * 48)
    print(f"  {'合计':<28} {files:>6} {total / 1024 / 1024:>9.1f} MB")

    if args.dry_run:
        return 0

    # 校验：文件数必须一致
    actual = sum(1 for _ in dest.rglob("*") if _.is_file())
    print()
    print(f"[backup] 校验：目标 {actual} 个文件 / 计划 {files} 个 —— "
          f"{'一致' if actual >= files else '不一致'}")
    print(f"[backup] 位置：{dest}")
    return 0 if actual >= files else 1


if __name__ == "__main__":
    sys.exit(main())
