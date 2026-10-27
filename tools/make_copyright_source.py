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

# 源代码的编排顺序：从底层到上层，让审查员能看出架构。
#
# ⚠️ 顺序是有讲究的，不只是"好看"：
#   软著规则是 —— 不足 60 页提交全部，≥60 页**只交前 30 页 + 后 30 页**。
#   我们当前超过 60 页，所以**中间会有一段被省略**。
#
#   因此把**测试/辅助代码**（Capability、OcrQuality、SelfCheck）放在中间，
#   保证被省掉的是"验证代码"而不是"实现代码"。
#   核心算法（types → pipeline）在前 30 页，界面与设备接入在后 30 页。
SOURCE_ORDER = [
    # —— 前 30 页：核心算法。这六个文件是这份软件的实质，必须完整可见 ——
    "lib/types.ts",
    "lib/tokenize.ts",
    "lib/index.ts",
    "lib/search.ts",
    "lib/pipeline.ts",
    "lib/ocr.ts",
    # —— 中间（≥60 页时整段省略）：自测与质量测试 ——
    #    刻意放在这里：省略它们不会让审查员看不懂功能实现。
    "selfcheck/Capability.ets",
    "selfcheck/OcrQuality.ets",
    "selfcheck/SelfCheck.ets",
    # —— 后 30 页：存储、设备接入与界面 ——
    #    store 排在自测之后，是为了让"被省略的区间"完整落在三个自测文件上，
    #    而不是切在某个实现文件的中间。顺序牺牲了一点阅读流畅，
    #    换取"提交的 60 页里包含全部实现代码"。
    "lib/store.ts",
    "lib/librarystorage.ets",
    "lib/realocr.ets",
    "pages/Index.ets",
    "entryability/EntryAbility.ets",
]

LINES_PER_PAGE = 50
# 软著：页数达到这个值时，只需提交前 N 页 + 后 N 页
FULL_SUBMIT_LIMIT = 60
EDGE_PAGES = 30

# 判定"被省略的部分会不会影响读懂核心功能"。
# 这几个文件是这份软件的技术实质，任何一个被切都要报警。
CRITICAL_FILES = {
    "lib/types.ts",
    "lib/tokenize.ts",
    "lib/index.ts",
    "lib/search.ts",
    "lib/pipeline.ts",
}


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

    print("=" * 72)
    print(f"软著源代码文档 —— {HEADER_TEXT}")
    print("=" * 72)
    print(f"  {'文件':<34}{'行数':>8}{'累计页':>8}")
    print("  " + "-" * 52)
    cum = 0
    for rel, n in stats:
        cum += n + 1  # +1 是文件分隔标记
        print(f"  {rel:<34}{n:>8}{cum / LINES_PER_PAGE:>7.1f}")
    print("  " + "-" * 52)
    print(f"  {'合计（去空行 + 文件分隔标记）':<34}{total:>8}")
    print()
    print(f"  每页 {LINES_PER_PAGE} 行  ->  {pages} 页")
    print()

    need_split = pages >= FULL_SUBMIT_LIMIT
    if not need_split:
        print(f"  {pages} 页 < {FULL_SUBMIT_LIMIT} 页  =>  软著要求「提交全部源代码」，正好适用。")
    else:
        omitted = pages - EDGE_PAGES * 2
        print(f"  {pages} 页 >= {FULL_SUBMIT_LIMIT} 页  =>  只提交「前 {EDGE_PAGES} 页 + 后 {EDGE_PAGES} 页」")
        print(f"  中间第 {EDGE_PAGES + 1}–{pages - EDGE_PAGES} 页（共 {omitted} 页）不提交。")
        print()
        # 算一下被省略的是哪几个文件 —— 这是排序是否合理的关键
        edge = EDGE_PAGES * LINES_PER_PAGE
        omitted_start, omitted_end = edge, total - edge
        cum = 0
        omitted_files = []
        for rel, n in stats:
            f_start, f_end = cum, cum + n + 1
            if f_end > omitted_start and f_start < omitted_end:
                omitted_files.append(rel)
            cum = f_end
        print(f"  被省略的代码落在：{('、'.join(omitted_files)) if omitted_files else '（无）'}")
        hit = sorted(CRITICAL_FILES & set(omitted_files))
        if hit:
            print(f"  [警告] 核心算法文件被省略：{('、'.join(hit))}")
            print("         需要调整 SOURCE_ORDER，把这些文件挪到前 30 页内。")
        else:
            print("  核心算法（types/tokenize/index/search/pipeline）全部在前 30 页，不受影响。")

    if args.check:
        return 0

    if need_split:
        # 一份完整版存档，一份提交版（只有前30+后30）
        edge = EDGE_PAGES * LINES_PER_PAGE
        submit_lines = lines[:edge] + lines[-edge:]
        full_out = OUT / f"{SOFTWARE_NAME}{VERSION}-源代码-完整存档.docx"
        sub_out = OUT / f"{SOFTWARE_NAME}{VERSION}-源代码-提交版.docx"
        n_full = build_doc(lines, full_out)
        n_sub = build_doc(submit_lines, sub_out)
        print()
        print(f"[src] 完整存档（内部参考，不提交）：{full_out.relative_to(ROOT)}")
        print(f"      {n_full} 页")
        print(f"[src] 提交版（{EDGE_PAGES} + {EDGE_PAGES} = {2 * EDGE_PAGES} 页）：{sub_out.relative_to(ROOT)}")
        print(f"      {n_sub} 页  <- 这一份上传到软著系统")
        n = n_sub
    else:
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
