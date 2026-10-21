#!/usr/bin/env python3
"""
生成软著登记用的源代码文档（.docx）。

WHY A GENERATOR AND NOT A MANUAL DOCUMENT
    软著对源代码文档有硬性格式要求：
      · 每页 50 行
      · 不含空行
      · 页眉含「软件名称 + 版本号」
      · 连续页码

    手工排版 1,910 行必然出错，而且代码一改就要重排。
    写成生成器之后，**代码改了重跑一次即可**，格式永远是对的。

    另外，页眉里的名称/版本号是与申请表、说明书必须完全一致的字段，
    集中在这一个常量里，避免三处不一致——那是软著最常见的退回原因之一。

USAGE
    python tools/make_copyright_source.py
    python tools/make_copyright_source.py --check   # 只统计，不生成
"""

import argparse
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Pt, Cm

ROOT = Path(__file__).resolve().parent.parent
ETS = ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "ets"
OUT = ROOT / "deliverables" / "软著登记"

# ---------------------------------------------------------------------------
# 必须与申请表、说明书完全一致的三个字段
# ---------------------------------------------------------------------------
SOFTWARE_NAME = "离线资料库软件"
VERSION = "V1.0"
HEADER_TEXT = f"{SOFTWARE_NAME} {VERSION}"

# 源代码的编排顺序：从底层到上层，让审查员能看出架构
SOURCE_ORDER = [
    "lib/types.ts",
    "lib/tokenize.ts",
    "lib/index.ts",
    "lib/search.ts",
    "lib/store.ts",
    "lib/ocr.ts",
    "lib/pipeline.ts",
    "pages/Index.ets",
    "selfcheck/SelfCheck.ets",
    "entryability/EntryAbility.ets",
]

LINES_PER_PAGE = 50


def read_source() -> tuple[list[str], list[tuple[str, int]]]:
    """读入全部源码，返回（去掉空行后的行列表, 每个文件的行数统计）。"""
    lines: list[str] = []
    stats: list[tuple[str, int]] = []
    for rel in SOURCE_ORDER:
        p = ETS / rel
        if not p.exists():
            print(f"[src] 警告：文件不存在，已跳过 —— {rel}")
            continue
        raw = p.read_text(encoding="utf-8").splitlines()
        kept = [ln.rstrip() for ln in raw if ln.strip() != ""]
        # 文件分隔标记，便于审查员看出模块边界
        lines.append(f"// ==================== {rel} ====================")
        lines.extend(kept)
        stats.append((rel, len(kept)))
    return lines, stats


def set_run_font(run, name: str, size: float):
    run.font.name = name
    run.font.size = Pt(size)
    r = run._element
    r.rPr.rFonts.set(qn("w:eastAsia"), name)


def build_doc(lines: list[str], out_path: Path):
    doc = Document()

    # 页边距：源代码文档要塞下 50 行，边距要小一些
    for section in doc.sections:
        section.top_margin = Cm(1.4)
        section.bottom_margin = Cm(1.4)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.4)

    # 页眉：软件名称 + 版本号
    hdr = doc.sections[0].header
    hp = hdr.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hrun = hp.add_run(HEADER_TEXT)
    set_run_font(hrun, "宋体", 9)

    # 正文：每 50 行一页
    pages = [lines[i:i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)]
    for pi, page_lines in enumerate(pages):
        for ln in page_lines:
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = Pt(0)
            pf.space_after = Pt(0)
            pf.line_spacing = Pt(9.6)
            run = p.add_run(ln if ln else " ")
            set_run_font(run, "Consolas", 7.5)
        if pi < len(pages) - 1:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return len(pages)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只统计，不生成文档")
    args = ap.parse_args()

    if not ETS.exists():
        print(f"[src] 源码目录不存在：{ETS}")
        return 2

    lines, stats = read_source()
    total = len(lines)
    pages = (total + LINES_PER_PAGE - 1) // LINES_PER_PAGE

    print("=" * 66)
    print(f"软著源代码文档 —— {HEADER_TEXT}")
    print("=" * 66)
    print(f"  {'文件':<34}{'行数':>8}")
    print("  " + "-" * 44)
    for rel, n in stats:
        print(f"  {rel:<34}{n:>8}")
    print("  " + "-" * 44)
    print(f"  {'合计（去空行 + 文件分隔标记）':<34}{total:>8}")
    print()
    print(f"  每页 {LINES_PER_PAGE} 行  ->  {pages} 页")
    print()
    if pages < 60:
        print(f"  {pages} 页 < 60 页  =>  软著要求「提交全部源代码」，正好适用。")
    else:
        print(f"  {pages} 页 >= 60 页  =>  只需提交前 30 页 + 后 30 页。")

    if args.check:
        return 0

    out = OUT / f"{SOFTWARE_NAME}{VERSION}-源代码.docx"
    n = build_doc(lines, out)
    print()
    print(f"[src] 已生成：{out.relative_to(ROOT)}")
    print(f"[src] {n} 页，页眉「{HEADER_TEXT}」")
    print()
    print("  提交前请确认：")
    print("   1. 用 Word/WPS 打开检查排版（本脚本只保证行数与页眉）")
    print("   2. 页码是否连续（python-docx 不自动加页码，需在 Word 里插入页脚页码）")
    print("   3. 软件名称与申请表、说明书三处完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
