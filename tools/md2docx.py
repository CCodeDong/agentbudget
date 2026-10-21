#!/usr/bin/env python3
"""
把 markdown 转成 .docx（用项目已有的 officegen 排版）。

WHY A CONVERTER
    软著说明书要交 .docx。先写 markdown 再转，好处是：
      · markdown 可 diff、可复用到课程报告
      · 排版由 officegen 统一，不用手工调

    只支持我们实际用到的 markdown 子集：
      标题（#/##/###）、段落、无序列表、有序列表、表格、代码块、引用块。

    不追求完整 Markdown 兼容 —— 遇到不认识的语法就当普通段落处理，
    **宁可排版粗糙也不丢内容**。

USAGE
    python tools/md2docx.py <输入.md> [输出.docx]
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from officegen import new_doc, h, para, bullets, code_block, table  # noqa: E402


def strip_inline(s: str) -> str:
    """去掉内联标记：**粗体**、`代码`、[链接](url)。"""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return s


def split_row(line: str) -> list[str]:
    """拆表格行。忽略首尾空段。"""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return [strip_inline(c) for c in cells]


def is_sep_row(line: str) -> bool:
    """表格的分隔行，如 |---|:---:|。"""
    return bool(re.fullmatch(r"\|[\s:|-]+\|?", line.strip())) and "-" in line


def convert(md_path: Path, out_path: Path) -> int:
    lines = md_path.read_text(encoding="utf-8").splitlines()

    # 标题与副标题：第一个 # 当标题，其后的 > 引用当副标题
    title = md_path.stem
    subtitle = ""
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("# "):
            title = strip_inline(ln[2:].strip())
            body_start = i + 1
            break
    for i in range(body_start, min(body_start + 8, len(lines))):
        if lines[i].startswith(">"):
            subtitle = strip_inline(lines[i].lstrip("> ").strip())
            break

    doc = new_doc(title, subtitle)

    i = body_start
    n = len(lines)
    stats = {"h": 0, "para": 0, "table": 0, "code": 0, "bullet": 0}

    while i < n:
        raw = lines[i]
        line = raw.rstrip()

        # 空行
        if line.strip() == "":
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{2,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1)) - 1   # ## -> 1, ### -> 2, #### -> 3
            h(doc, strip_inline(m.group(2).strip()), level=min(max(level, 1), 3))
            stats["h"] += 1
            i += 1
            continue

        # 代码块
        if line.strip().startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            code_block(doc, "\n".join(buf))
            stats["code"] += 1
            continue

        # 表格
        if line.strip().startswith("|") and i + 1 < n and is_sep_row(lines[i + 1]):
            headers = split_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            table(doc, headers, rows)
            stats["table"] += 1
            continue

        # 无序列表
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(strip_inline(re.sub(r"^\s*[-*]\s+", "", lines[i]).strip()))
                i += 1
            bullets(doc, items)
            stats["bullet"] += len(items)
            continue

        # 有序列表
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(strip_inline(re.sub(r"^\s*\d+\.\s+", "", lines[i]).strip()))
                i += 1
            bullets(doc, items)
            stats["bullet"] += len(items)
            continue

        # 引用块
        if line.strip().startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(strip_inline(lines[i].lstrip("> ").strip()))
                i += 1
            for b in buf:
                if b:
                    para(doc, b)
                    stats["para"] += 1
            continue

        # 普通段落（合并连续的普通行）
        buf = [strip_inline(line.strip())]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (nxt == "" or nxt.startswith("#") or nxt.startswith("|")
                    or nxt.startswith("```") or nxt.startswith(">")
                    or re.match(r"^[-*]\s+", nxt) or re.match(r"^\d+\.\s+", nxt)):
                break
            buf.append(strip_inline(nxt))
            i += 1
        para(doc, " ".join(buf))
        stats["para"] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return stats


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    md = Path(sys.argv[1])
    if not md.is_absolute():
        md = ROOT / md
    if not md.exists():
        print(f"[md2docx] 输入不存在：{md}")
        return 2
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else md.with_suffix(".docx")
    if not out.is_absolute():
        out = ROOT / out

    stats = convert(md, out)
    print(f"[md2docx] 已生成：{out}")
    print(f"          标题 {stats['h']} / 段落 {stats['para']} / "
          f"表格 {stats['table']} / 代码块 {stats['code']} / 列表项 {stats['bullet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
