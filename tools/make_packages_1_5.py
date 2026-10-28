#!/usr/bin/env python3
"""
组装两个自包含的课程材料包：移动项目1.5 / 仓颉项目1.5。

WHY A SCRIPT
    材料包要能被老师单独拿走就用，所以必须**自包含**——
    报告、PPT、图表、截图、软著、上架材料、源码，一样不缺。

    手工复制的问题是：改了代码或补了材料之后，包里的东西会悄悄过时
    （这次就发生过：包里还是旧的 48 页源代码文档，而实际提交的是 60 页）。

    写成脚本后，"更新材料包"变成重跑一次，不会漏。

ABOUT VERSION NUMBERS
    这里有**两个不同的版本号**，不能混：
      · 材料包版本   1.5     —— 这份交付物的迭代编号
      · 软著登记版本 V1.0    —— 已提交到版权中心，证书上就是这个
    所以软著文件名保持 V1.0，只是被放进 1.5 的材料包里。

USAGE
    python tools/make_packages_1_5.py
    python tools/make_packages_1_5.py --dry-run
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELIV = ROOT / "deliverables"
PKG_MOBILE = DELIV / "移动项目1.5"
PKG_CJ = DELIV / "仓颉项目1.5"

# 复制规则：源路径 -> 包内相对路径
MOBILE_COPIES = [
    # 报告与 PPT（真正的课程交付物）
    (DELIV / "移动应用开发" / "立项.pptx", "报告与PPT/移动应用开发-立项答辩.pptx"),
    (DELIV / "移动应用开发" / "答辩.pptx", "报告与PPT/移动应用开发-结课答辩.pptx"),
    (DELIV / "移动应用开发" / "课程设计报告.docx", "报告与PPT/移动应用开发-课程设计报告.docx"),
    # 软著（已提交版本，注意是 V1.0）
    (DELIV / "软著登记" / "离线资料库软件V1.0-源代码-提交版.pdf", "软著/离线资料库软件V1.0-源代码-提交版.pdf"),
    (DELIV / "软著登记" / "离线资料库软件V1.0-软件说明书.pdf", "软著/离线资料库软件V1.0-软件说明书.pdf"),
    (DELIV / "软著登记" / "离线资料库软件V1.0-源代码-完整存档.docx", "软著/离线资料库软件V1.0-源代码-完整存档.docx"),

    # 关键文档
    (ROOT / "docs" / "ArkTS测试策略.md", "关键文档/ArkTS测试策略.md"),
    (ROOT / "docs" / "12周上架执行计划.md", "关键文档/12周上架执行计划.md"),
    (ROOT / "docs" / "AGC签名申请指南.md", "关键文档/AGC签名申请指南.md"),
    (ROOT / "docs" / "软著填表指南.md", "关键文档/软著填表指南.md"),
    (ROOT / "docs" / "软著登记材料清单.md", "关键文档/软著登记材料清单.md"),
    # 论文初稿（研究点的共同产出）
    (ROOT / "paper" / "01-论文初稿.md", "论文/01-论文初稿.md"),
    (ROOT / "paper" / "02-参考文献.md", "论文/02-参考文献.md"),
]

MOBILE_TREES = [
    # 上架材料（整个目录）
    (DELIV / "上架材料", "上架材料"),
    # 软著提交存档：冻结副本 + SHA256，软著若收到补正通知要靠它答复
    (DELIV / "软著登记" / "提交存档-2026R11L3771548", "软著/提交存档-2026R11L3771548"),
    # 分级验证证据 L3–L11：每个阶段一个目录，含截图与验证记录
    (DELIV / "演示素材", "验证证据"),
    # 应用源码（ArkTS 侧）
    (ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "ets", "源码/应用-ets"),
    # 核心库（含测试与评估，可脱离设备在 Node 里跑）
    (ROOT / "projects" / "offlinelib-core" / "src", "源码/核心库-src"),
    (ROOT / "projects" / "offlinelib-core" / "test", "源码/核心库-test"),
    (ROOT / "projects" / "offlinelib-core" / "eval", "源码/核心库-eval"),
    (ROOT / "projects" / "offlinelib-core" / "bench", "源码/核心库-bench"),
]

CJ_COPIES = [
    (DELIV / "仓颉语言" / "立项.pptx", "报告与PPT/仓颉语言-立项答辩.pptx"),
    (DELIV / "仓颉语言" / "答辩.pptx", "报告与PPT/仓颉语言-结课答辩.pptx"),
    (DELIV / "仓颉语言" / "课程设计报告.docx", "报告与PPT/仓颉语言-课程设计报告.docx"),
    # 研究结论类文档（这几份是论文与答辩的证据来源）
    (ROOT / "docs" / "02-仓颉技术验证报告.md", "关键文档/02-仓颉技术验证报告.md"),
    (ROOT / "docs" / "06-实验管线验证结果.md", "关键文档/06-实验管线验证结果.md"),
    (ROOT / "docs" / "07-压缩代价实验.md", "关键文档/07-压缩代价实验.md"),
    (ROOT / "docs" / "08-k扫描与Pareto前沿.md", "关键文档/08-k扫描与Pareto前沿.md"),
    (ROOT / "docs" / "09-消息表示实验.md", "关键文档/09-消息表示实验.md"),
    (ROOT / "docs" / "13-自适应k的负面结果.md", "关键文档/13-自适应k的负面结果.md"),
    (ROOT / "docs" / "14-得分驱动自适应k.md", "关键文档/14-得分驱动自适应k.md"),
    (ROOT / "docs" / "12-摘要预算敏感性.md", "关键文档/12-摘要预算敏感性.md"),
    # 论文初稿（研究点的共同产出）
    (ROOT / "paper" / "01-论文初稿.md", "论文/01-论文初稿.md"),
    (ROOT / "paper" / "02-参考文献.md", "论文/02-参考文献.md"),
]

CJ_TREES = [
    (ROOT / "projects" / "agentbudget4cj" / "src", "源码/src"),
    # 全部实验结果（原始 CSV/JSON，是实验结论的依据，**不能重新生成**）
    (ROOT / "experiments" / "results", "实验数据/results"),
    (ROOT / "experiments" / "results_adaptive", "实验数据/results_adaptive"),
    (ROOT / "experiments" / "results_codec_cost", "实验数据/results_codec_cost"),
    (ROOT / "experiments" / "results_ksweep", "实验数据/results_ksweep"),
    (ROOT / "experiments" / "results_mt_smoke", "实验数据/results_mt_smoke"),
    (ROOT / "experiments" / "results_multiturn", "实验数据/results_multiturn"),
    (ROOT / "experiments" / "results_pool15", "实验数据/results_pool15"),
    (ROOT / "experiments" / "results_pool15_fixed", "实验数据/results_pool15_fixed"),
    (ROOT / "experiments" / "results_pool5_fixed", "实验数据/results_pool5_fixed"),
    (ROOT / "experiments" / "results_score_k", "实验数据/results_score_k"),
    (ROOT / "experiments" / "results_smoke", "实验数据/results_smoke"),
    (ROOT / "experiments" / "results_sumbudget", "实验数据/results_sumbudget"),
]

# 需要从 packages 里排除的噪音
SKIP_NAMES = {"__pycache__", "_tmp", "target", "dist", "node_modules",
              "_hvhome", "_npmcache", "build", "_out", ".git", ".idea"}


def copy_file(src: Path, dst: Path, stats: dict):
    if not src.exists():
        stats["missing"].append(str(src.relative_to(ROOT)))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    stats["files"] += 1
    stats["bytes"] += src.stat().st_size


def copy_tree(src: Path, dst: Path, stats: dict, dry: bool):
    if not src.exists():
        stats["missing"].append(str(src.relative_to(ROOT)))
        return
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        out = dst / rel
        if dry:
            stats["files"] += 1
            stats["bytes"] += p.stat().st_size
        else:
            copy_file(p, out, stats)


def build_package(pkg: Path, copies, trees, stats: dict, dry: bool):
    for src, rel in copies:
        if dry:
            if src.exists():
                stats["files"] += 1
                stats["bytes"] += src.stat().st_size
            else:
                stats["missing"].append(str(src.relative_to(ROOT)))
        else:
            copy_file(src, pkg / rel, stats)
    for src, rel in trees:
        copy_tree(src, pkg / rel, stats, dry)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    results = {}
    for name, pkg, copies, trees in [
        ("移动项目1.5", PKG_MOBILE, MOBILE_COPIES, MOBILE_TREES),
        ("仓颉项目1.5", PKG_CJ, CJ_COPIES, CJ_TREES),
    ]:
        print("=" * 72)
        print(f"组装 {name}")
        print("=" * 72)
        stats = {"files": 0, "bytes": 0, "missing": []}
        build_package(pkg, copies, trees, stats, args.dry_run)
        print(f"  复制 {stats['files']} 个文件，{stats['bytes'] / 1024 / 1024:.1f} MB")
        if stats["missing"]:
            print(f"  [缺] {len(stats['missing'])} 个来源不存在：")
            for m in stats["missing"]:
                print(f"       {m}")
        print()
        results[name] = stats

    if not args.dry_run:
        # 统计整个包（含原有的图表/截图）的最终规模
        print("=" * 72)
        print("最终规模")
        print("=" * 72)
        for name, pkg in [("移动项目1.5", PKG_MOBILE), ("仓颉项目1.5", PKG_CJ)]:
            fs = [p for p in pkg.rglob("*") if p.is_file()]
            total = sum(p.stat().st_size for p in fs)
            print(f"  {name:<14} {len(fs):>4} 文件  {total / 1024 / 1024:>7.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
