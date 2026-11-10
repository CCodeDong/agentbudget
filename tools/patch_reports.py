#!/usr/bin/env python3
"""
修补开题报告封面 + 脱敏 Git 指南。

背景
  2026-11-10 复核发现：两份报告的封面回到了未修补状态
  （成员行含组长、缺指导教师与小组名称）。进度表的修复仍在。

本脚本做的事
  1. 成员行改为只列「李丛容、陈皖」（组长已单列，不应重复）
  2. 在成员行**之后**插入「指导教师」与「小组名称」——用 addnext 保证顺序，
     而不是 insert_paragraph_before（后者会让两行都跑到成员行前面）
  3. 写入的文本**不含 markdown 星号**，避免原样印出
  4. `docs/Git-GitHub同步指南.md` 里的真实邮箱与 GitCode 身份脱敏
     （该文件已公开可见，不应含个人信息）

USAGE
    python tools/patch_reports.py
"""

import re
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "立项"

TEACHER = "谢涛"
MEMBERS = "李丛容、陈皖"

COURSES = {
    "《移动应用开发》项目开题报告.docx": "隔壁老王说的队",
    "《仓颉语言程序设计》项目开题报告.docx": "第六组-仓颉开天辟地补天射日填海捣药造字组",
}


def _set(run, size=18, bold=False):
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(size)
    run.font.bold = bold


def _insert_after(anchor, text):
    """在 anchor 段落之后插入一段并写入 text，返回新段落。

    python-docx 没有 insert_paragraph_after，这里用底层 lxml：
    先造一个段，从原位置摘掉，再挂到 anchor 之后。
    """
    new = anchor.insert_paragraph_before()
    new._p.getparent().remove(new._p)
    anchor._p.addnext(new._p)
    for r in list(new.runs):
        r.text = ""
    _set(new.add_run(text))
    return new


def patch_cover(f: Path, group: str):
    doc = Document(f)
    member = None
    for p in doc.paragraphs:
        if p.text.strip().startswith("项 目 成 员"):
            member = p
            break
    if member is None:
        print("    ⚠️ 找不到成员行")
        return

    # 1) 成员行：保留标签，只换人名
    for r in list(member.runs):
        r.text = ""
    _set(member.add_run(f"项 目 成 员：　{MEMBERS}"))
    print(f"    ✅ 成员行 → 项 目 成 员：{MEMBERS}")

    last = member
    have = "\n".join(p.text for p in doc.paragraphs)

    if "指 导 教 师" not in have:
        np = _insert_after(last, f"指 导 教 师：　{TEACHER}")
        np.alignment = member.alignment
        last = np
        print(f"    ✅ 补「指导教师：{TEACHER}」")

    if group not in have:
        np = _insert_after(last, f"小 组 名 称：　{group}")
        np.alignment = member.alignment
        print(f"    ✅ 补「小组名称：{group}」")

    doc.save(f)


def scrub_git_guide():
    """Git 指南已公开，脱敏真实邮箱与 GitCode 身份。"""
    f = ROOT / "docs" / "Git-GitHub同步指南.md"
    if not f.exists():
        return
    t = f.read_text(encoding="utf-8")
    before = t
    t = re.sub(r"CCodeDong <\d+@qq\.com>", "你的用户名 <你的 GitHub 邮箱>", t)
    t = re.sub(r'"\d+@qq\.com"', '"你的GitHub邮箱"', t)
    t = re.sub(r"2603_\d+@noreply\.gitcode\.com", "你的GitCode身份@noreply.gitcode.com", t)
    t = re.sub(r"2603_\d+", "你的GitCode用户名", t)
    if t != before:
        if "本文件已脱敏" not in t:
            note = ("\n> ⚠️ **本文件已脱敏**：仓库公开后，文中真实邮箱与 GitCode 身份已替换为占位符。\n"
                    "> 你自己配置时请填真实值。\n")
            lines = t.split("\n")
            for i, l in enumerate(lines):
                if l.startswith("# "):
                    lines.insert(i + 2, note)
                    break
            t = "\n".join(lines)
        f.write_text(t, encoding="utf-8")
        print(f"    ✅ 已脱敏（{len(before)} → {len(t)} 字符）")
    else:
        print("    ⏭ 无需改动")


def main():
    for fname, group in COURSES.items():
        f = D / fname
        if not f.exists():
            print(f"  [跳过] {fname}")
            continue
        print(f"\n[{fname}]")
        patch_cover(f, group)
        print(f"    已保存（{f.stat().st_size:,} B）")

    print("\n[docs/Git-GitHub同步指南.md]")
    scrub_git_guide()
    return 0


if __name__ == "__main__":
    sys.exit(main())
