#!/usr/bin/env python3
"""
冻结检索评估语料（`eval-corpus/`）。

WHY
    原先 `olib.py eval` 直接扫描仓库根目录的 markdown。这有两个问题：
      1. 仓库内容会变（整理目录、改写文档、增删记录），**同一个指标会漂移**；
      2. 归档目录 `旧版/` 里的重复文档会被一并计入，语料里混入副本。

    2026-11-04 的目录整理就使"精确率"从 89.4% 变成 59.9%——
    两个数各自都真实，但**被测对象不是同一批文档**。
    这与论文 §7.8 记录的"跨实现版本比较"是同一种错误：数字对，对象错。

    解法是让基准**不再随仓库漂移**：把语料冻结成一份带哈希的副本，
    评测只读这份副本。此后仓库怎么变，这个数字都可比。

选择规则
    纳入：仓库内的项目文档（`docs/`、`deliverables/`、`projects/`、根目录报告等）
    排除：`旧版/`（归档副本）、`paper/`（避免用论文自身做评测语料）、
          构建产物、依赖目录、隐藏目录

USAGE
    python tools/make_eval_corpus.py           # 重建 eval-corpus/ 与清单
    python tools/make_eval_corpus.py --check   # 只校验清单与磁盘是否一致
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "eval-corpus"
MANIFEST = DEST / "MANIFEST.json"

# 目录名级排除
EXCLUDE_DIRS = {
    "旧版", "paper", "_v0.2-备份", "_stage", "_stage2", "_out",
    "node_modules", "oh_modules", "dist", "build", "target",
    ".git", ".hvigor", ".idea", "_hvhome", "_npmcache", "__pycache__",
    "eval-corpus", "stdx", "samples",
}

# 与语料评估一致的最小体积（eval 里只收 > 800 B 的文档）
MIN_BYTES = 800


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect():
    """返回纳入语料的源文件列表（绝对路径，已排序）。"""
    out = []
    for p in ROOT.rglob("*.md"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.stat().st_size <= MIN_BYTES:
            continue
        out.append(p)
    return sorted(out)


def build():
    files = collect()
    if not files:
        print("  ❌ 没有找到符合条件的文档")
        return 2

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    entries = []
    total = 0
    for src in files:
        rel = src.relative_to(ROOT)
        # 扁平化会导致同名覆盖，保留相对路径
        dst = DEST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        h = sha256(dst)
        entries.append({"path": str(rel).replace("\\", "/"), "bytes": dst.stat().st_size, "sha256": h})
        total += dst.stat().st_size

    manifest = {
        "purpose": "检索评估的冻结语料；评测只读本目录，不随仓库内容漂移",
        "created": "2026-11-10",
        "rule": "仓库内 .md，>800 B；排除 旧版/ paper/ stdx/ samples/ 与构建产物",
        "file_count": len(entries),
        "total_bytes": total,
        "files": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  ✅ 冻结 {len(entries)} 篇文档，共 {total/1024:.0f} KB")
    print(f"     目录: {DEST.relative_to(ROOT)}/")
    print(f"     清单: {MANIFEST.relative_to(ROOT)}")
    return 0


def check():
    if not MANIFEST.exists():
        print("  ❌ 找不到 MANIFEST.json，先跑一次 build")
        return 2
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = []
    for e in m["files"]:
        p = DEST / e["path"]
        if not p.exists():
            bad.append(("缺失", e["path"]))
        elif sha256(p) != e["sha256"]:
            bad.append(("哈希不符", e["path"]))
    extra = [str(p.relative_to(DEST)) for p in DEST.rglob("*.md")
             if str(p.relative_to(DEST)).replace("\\", "/") not in {e["path"] for e in m["files"]}]
    print(f"  清单声明 {m['file_count']} 篇 / {m['total_bytes']/1024:.0f} KB")
    print(f"  磁盘实际 {len(list(DEST.rglob('*.md')))} 篇")
    if bad:
        print(f"  ❌ {len(bad)} 处不一致")
        for kind, path in bad[:8]:
            print(f"      {kind}: {path}")
        return 1
    if extra:
        print(f"  ⚠️ 清单外多出 {len(extra)} 篇（不影响评测，但清单应重生成）")
    print("  ✅ 清单与磁盘一致")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    return check() if a.check else build()


if __name__ == "__main__":
    sys.exit(main())
