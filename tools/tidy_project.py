#!/usr/bin/env python3
"""
项目目录整理（2026-11-04）。

原则
  1. **完全重复的删除**（每个被删文件都能在别处按哈希找到），
  2. **有独有内容的移入 `旧版/`，不删**，
  3. **构建产物与缓存清理**（可再生产）。

安全
  所有被删文件都在 git 里，`git log --diff-filter=D -- <path>` 可找回。
  重复判定用 SHA256，不靠文件名。

USAGE
    python tools/tidy_project.py --dry-run    # 先看清单
    python tools/tidy_project.py              # 执行
"""

import argparse
import hashlib
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "旧版"

# 不参与哈希统计的目录
SKIP_DIRS = {"stdx", "_research", ".git", "旧版", "_stage"}
SKIP_PARTS = {"_out", "oh_modules", "node_modules", "build", "target", "dist"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def scan():
    """返回 hash -> [相对路径]。"""
    by = defaultdict(list)
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(x in SKIP_DIRS for x in rel.parts):
            continue
        if any(x in SKIP_PARTS for x in rel.parts):
            continue
        try:
            by[sha(p)].append(rel)
        except OSError:
            pass
    return by


def is_fully_duplicated(folder: Path, by: dict) -> bool:
    """目录里每个文件的哈希都能在目录外找到 → 整目录可删。"""
    folder = folder.resolve()
    files = [p for p in folder.rglob("*") if p.is_file()]
    if not files:
        return False
    for p in files:
        rel = p.relative_to(ROOT)
        others = [q for q in by[sha(p)] if q != rel]
        if not others:
            return False
    return True


def sweep_build_artifacts(dry: bool):
    """删构建产物与缓存（可再生）。"""
    removed = 0
    bytes_freed = 0
    for pat in [
        ROOT / "app" / "harmony" / "entry" / "build",
        ROOT / "app" / "harmony" / ".hvigor",
        ROOT / "app" / "harmony" / "_hvhome",
        ROOT / "app" / "harmony" / "_npmcache",
        ROOT / "projects" / "agentbudget4cj" / "target",
        ROOT / "projects" / "offlinelib-core" / "dist",
    ]:
        if pat.exists():
            size = sum(p.stat().st_size for p in pat.rglob("*") if p.is_file())
            print(f"  [构建产物] {pat.relative_to(ROOT)}  ({size/1024/1024:.1f} MB)")
            if not dry:
                shutil.rmtree(pat, ignore_errors=True)
            removed += 1
            bytes_freed += size
    for d in ROOT.rglob("__pycache__"):
        if d.is_dir() and not dry:
            shutil.rmtree(d, ignore_errors=True)
    return removed, bytes_freed


def _stat(p: Path):
    """返回 (文件数, 字节数)。目录与单文件都支持。"""
    if p.is_file():
        return 1, p.stat().st_size
    files = [q for q in p.rglob("*") if q.is_file()]
    return len(files), sum(q.stat().st_size for q in files)


def archive(src: Path, dest_rel: str, dry: bool):
    dest = ARCHIVE / dest_rel
    n, size = _stat(src)
    print(f"  [移入旧版] {src.relative_to(ROOT)}  →  旧版/{dest_rel}  ({n} 文件, {size/1024/1024:.2f} MB)")
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(src), str(dest))
    return size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    print("=" * 74)
    print("项目目录整理" + ("（DRY RUN，不实际改动）" if dry else ""))
    print("=" * 74)

    # ---------- 阶段 0：先清理构建产物，避免它们干扰哈希统计 ----------
    print("\n【阶段 0】清理构建产物与缓存")
    n0, b0 = sweep_build_artifacts(dry)
    print(f"  共 {n0} 项，{b0/1024/1024:.1f} MB")

    # ---------- 阶段 1：重新扫描（构建产物已清） ----------
    by = scan()

    # ---------- 阶段 2：完全重复 → 删除 ----------
    print("\n【阶段 1】完全重复的目录（整目录删除）")
    full_dupes = [
        "deliverables/移动应用开发",
        "deliverables/仓颉语言",
        "deliverables/演示素材",
    ]
    freed = 0
    for rel in full_dupes:
        d = ROOT / rel
        if not d.exists():
            print(f"  [跳过] {rel} 不存在")
            continue
        if is_fully_duplicated(d, by):
            size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            n = sum(1 for p in d.rglob("*") if p.is_file())
            print(f"  [删除] {rel}  ({n} 文件, {size/1024/1024:.2f} MB) —— 全部文件在别处有副本")
            if not dry:
                shutil.rmtree(d)
            freed += size
        else:
            print(f"  [保留] {rel} —— 含独有文件，不删")

    # 无关目录
    for rel in ["_research"]:
        d = ROOT / rel
        if d.exists():
            size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            n = sum(1 for p in d.rglob("*") if p.is_file())
            print(f"  [删除] {rel}  ({n} 文件, {size/1024/1024:.1f} MB) —— 与本项目无关（网页小游戏）")
            if not dry:
                shutil.rmtree(d)
            freed += size

    # ---------- 阶段 3：有独有内容或旧版本 → 旧版 ----------
    print("\n【阶段 2】移入 旧版/（保留，不删）")
    moves = [
        ("deliverables/开题答辩素材", "01-开题答辩素材-移动"),
        ("deliverables/开题答辩素材-仓颉", "02-开题答辩素材-仓颉"),
        ("deliverables/PPT材料", "03-PPT材料"),
        ("deliverables/上架材料", "04-上架材料-早期"),
        ("deliverables/软著申请", "05-软著-早期版本-1024"),
        ("deliverables/软著登记", "06-软著-登记版-1028"),
        ("团队同步-项目说明.md", "08-过时文档/团队同步-项目说明-1008.md"),
        ("项目进度报告.md", "08-过时文档/项目进度报告-1021.md"),
    ]
    archived = 0
    for rel, dest in moves:
        p = ROOT / rel
        if p.exists():
            archived += archive(p, dest, dry)
        else:
            print(f"  [跳过] {rel} 不存在")

    # ---------- 阶段 4：_out 里的 PPT 工作版本 → 旧版，其余删除 ----------
    print("\n【阶段 3】_out/：PPT 工作版本归档，审计临时文件删除")
    out = ROOT / "_out"
    if out.exists():
        keeps = sorted(out.glob("*.pptx"))
        keep_bytes = sum(f.stat().st_size for f in keeps)
        if keeps:
            dest = ARCHIVE / "07-PPT工作版本"
            if not dry:
                dest.mkdir(parents=True, exist_ok=True)
            for f in keeps:
                print(f"  [归档] _out/{f.name}  ({f.stat().st_size/1024/1024:.1f} MB)")
                if not dry:
                    shutil.move(str(f), str(dest / f.name))
        rest = [p for p in out.rglob("*") if p.is_file()]
        # 归档的文件已经搬走，这里的 rest 在 dry-run 下仍包含它们，需扣掉
        rest_bytes = sum(p.stat().st_size for p in rest) - (0 if dry else 0)
        if dry:
            rest_bytes -= keep_bytes
            rest = [p for p in rest if p.suffix.lower() != ".pptx" or p not in keeps]
        print(f"  [删除] _out/ 剩余 {len(rest)} 个审计/临时文件  ({rest_bytes/1024/1024:.2f} MB)")
        if not dry:
            shutil.rmtree(out, ignore_errors=True)

    # ---------- 汇总 ----------
    print("\n" + "=" * 74)
    print(f"  删除释放 : {freed/1024/1024:.1f} MB")
    print(f"  归档体积 : {archived/1024/1024:.1f} MB → 旧版/")
    print(f"  构建产物 : {b0/1024/1024:.1f} MB")
    print("=" * 74)
    if dry:
        print("\n未做实际改动。去掉 --dry-run 执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
