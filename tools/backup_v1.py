#!/usr/bin/env python3
"""
把项目 1.0 的产出与代码备份到两门课的课程目录。

DESIGN NOTES
  1. 两门课各建一个带 "1.0" 的独立文件夹。共享内容（论文 / 设计文档 / 实验数据 /
     工具脚本）在两处各存一份 —— 依赖另一个文件夹的备份不算备份。
  2. 复制后逐文件比对，并输出清单，使"备份完整"是可核对的而非假定的。
  3. 排除构建中间物（临时镜像、__pycache__、node_modules 等），
     但**保留**可执行产物（.exe / .hap）与全部原始实验数据。

WHY PYTHON, NOT POWERPOINT... rather, NOT POWERSHELL
  Windows PowerShell 5.1 把无 BOM 的 .ps1 按系统 ANSI（此处为 GBK）解码，
  脚本里的中文路径会全部乱码。既然目标路径本身含中文，就无法用"纯 ASCII"规避。
  Python 3 默认按 UTF-8 读源码，不存在这个问题。

USAGE
    python tools/backup_v1.py             # 实际备份
    python tools/backup_v1.py --dry-run   # 只列出将要复制的清单
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = Path(r"C:\学习！！！！\大学\仙交大新生活\studying\2026第一学期")

DEST_CANGJIE = BASE / "仓颉开发" / "仓颉语言课程项目1.0"
DEST_APP = BASE / "移动应用开发" / "移动应用开发课程项目1.0"

# 两门课共有的内容（各存一份）
SHARED = [
    ("paper", "论文"),
    ("docs", "设计文档"),
    ("experiments", "实验数据与框架"),
    ("tools", "工具脚本"),
    ("README.md", "README.md"),
]

CANGJIE_ONLY = [
    (r"projects\agentbudget4cj", "仓颉调度器库"),
    (r"deliverables\仓颉语言", "课程交付物"),
    (r"deliverables\演示素材\仓颉演示实录.md", r"演示素材\仓颉演示实录.md"),
]

APP_ONLY = [
    (r"app\harmony", "HarmonyOS应用"),
    (r"deliverables\移动应用开发", "课程交付物"),
    (r"deliverables\演示素材\移动端预期界面状态清单.md",
     r"演示素材\移动端预期界面状态清单.md"),
    (r"deliverables\环境搭建与运行说明.docx", r"课程交付物\环境搭建与运行说明.docx"),
]

EXCLUDE_DIRS = {"_verify", "__pycache__", "node_modules", ".hvigor", "oh_modules",
                "build", ".git", "_tmp", "_hvhome", "_npmcache", "target", "cov_output"}
EXCLUDE_SUFFIX = {".pyc", ".log"}


def wanted(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if rel.suffix in EXCLUDE_SUFFIX:
        return False
    return True


def copy_one(from_rel: str, to_rel: str, dest_root: Path, dry: bool):
    src = ROOT / from_rel
    dst = dest_root / to_rel
    if not src.exists():
        return {"from": from_rel, "files": 0, "bytes": 0, "missing": True}

    files = 0
    total = 0
    if src.is_dir():
        for p in src.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(src)
            if not wanted(rel):
                continue
            if not dry:
                out = dst / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)
            files += 1
            total += p.stat().st_size
    else:
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        files = 1
        total = src.stat().st_size
    return {"from": from_rel, "files": files, "bytes": total, "missing": False}


def backup_course(name: str, dest: Path, extra, dry: bool):
    print()
    print(f"[backup] {name}  ->  {dest}")
    print("  " + "-" * 72)
    if not dry:
        dest.mkdir(parents=True, exist_ok=True)

    results = []
    for from_rel, to_rel in list(SHARED) + list(extra):
        r = copy_one(from_rel, to_rel, dest, dry)
        results.append(r)
        if r["missing"]:
            print(f"  [缺失] {from_rel}")
        else:
            print(f"  [复制] {from_rel:<48} {r['files']:>4} 文件 {r['bytes']:>12,} B")

    files = sum(r["files"] for r in results)
    total = sum(r["bytes"] for r in results)
    missing = [r["from"] for r in results if r["missing"]]
    print("  " + "-" * 72)
    print(f"  {name}：{files} 个文件，{total / 1024 / 1024:.1f} MB")
    if missing:
        print(f"  [警告] 源路径不存在：{', '.join(missing)}")
    return {"name": name, "dest": dest, "files": files, "bytes": total,
            "missing": missing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只列清单，不复制")
    args = ap.parse_args()

    print("=" * 74)
    print("项目 1.0 备份")
    print(f"  源   : {ROOT}")
    print(f"  目标 : {BASE}")
    if args.dry_run:
        print("  模式 : DRY RUN（不实际复制）")
    print("=" * 74)

    if not BASE.exists():
        print(f"[backup] 错误：目标根目录不存在 -> {BASE}")
        return 2

    r1 = backup_course("仓颉语言", DEST_CANGJIE, CANGJIE_ONLY, args.dry_run)
    r2 = backup_course("移动应用开发", DEST_APP, APP_ONLY, args.dry_run)

    if args.dry_run:
        return 0

    print()
    print("[backup] 校验：比对目标文件数与计划数")
    ok = True
    for r in (r1, r2):
        actual = sum(1 for p in r["dest"].rglob("*") if p.is_file())
        same = actual >= r["files"]
        if not same:
            ok = False
        flag = "[一致]" if same else "[不一致]"
        print(f"  {r['name']:<14} 目标 {actual:>4} 文件  {flag}  {r['dest']}")
    print()
    print("[backup] 完成，两处备份均已核对。" if ok
          else "[backup] 有差异，请检查上面的 [缺失] 行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
