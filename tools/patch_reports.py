#!/usr/bin/env python3
"""
在**现有**开题报告上做定点修改（不重新生成，避免覆盖人工修订）。

改什么
  1. 封面「项目成员」去掉重复的组长（组长已单列）
  2. 封面补「指导教师」与「小组名称」（小组名按各课程 PPT 取值）
  3. 移动报告的进度表修正软著状态 —— 实际 2026-10-28 已提交
     （流水号 2026R11L3771548，待受理），原稿写成 W9–W10 待办

USAGE
    python tools/patch_reports.py
"""

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "立项"

TEACHER = "谢涛"
MEMBERS = "李丛容、陈皖"

# 小组名按各课程 PPT 封面取值
COURSES = {
    "《移动应用开发》项目开题报告.docx": "隔壁老王说的队",
    "《仓颉语言程序设计》项目开题报告.docx": "第六组-仓颉开天辟地补天射日填海捣药造字组",
}


def _cn(run, size=18):
    run.font.name = "宋体"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    run.font.size = Pt(size)


def fix_cover(doc, group_name):
    paras = doc.paragraphs
    for p in paras:
        t = p.text.strip()
        # 成员行去重：组长已单列，成员不应再含组长
        if t.startswith("项 目 成 员"):
            for r in list(p.runs):
                r.text = ""
            _cn(p.add_run(f"　{MEMBERS}"))
            print(f"    ✅ 成员改为：{MEMBERS}")
            break

    # 在成员行之后插入 指导教师 / 小组名称
    anchor = None
    for p in paras:
        if p.text.strip().startswith("项 目 成 员"):
            anchor = p
            break
    if anchor is None:
        print("    ⚠️ 找不到成员行")
        return

    have = "\n".join(x.text for x in paras)
    if "指导教师" in have and TEACHER in have:
        print("    ⏭ 指导教师已存在")
    else:
        newp = anchor.insert_paragraph_before()
        newp.alignment = anchor.alignment
        _cn(newp.add_run(f"指 导 教 师：　{TEACHER}"))
        print(f"    ✅ 已补指导教师：{TEACHER}")

    if group_name in have:
        print("    ⏭ 小组名称已存在")
    else:
        newp2 = anchor.insert_paragraph_before()
        newp2.alignment = anchor.alignment
        _cn(newp2.add_run(f"小 组 名 称：　{group_name}"))
        print(f"    ✅ 已补小组名称：{group_name}")


def fix_mobile_schedule(doc):
    """移动报告：进度表按实际状态修正（软著已提交）。"""
    reps = {
        "第 7 至 8 周：完成 OCR 在 12 种退化条件下的质量测试与置信度信号验证；补齐资料详情页、编辑与删除确认；完成深色模式与宽屏适配。":
        "第 7 周（当前）：完成 OCR 在 12 种退化条件下的质量测试与置信度信号验证；补齐资料详情页、编辑与删除确认；"
        "完成深色模式与宽屏适配；上架四项材料备齐。**软著已于 10 月 28 日提交**"
        "（流水号 2026R11L3771548，状态待受理）。",
        "第 9 至 10 周：整理软著登记材料（源代码前后各 30 页、软件说明书）并完成提交；准备隐私政策、应用图标、商店文案等上架材料。":
        "第 8 至 9 周：申请 AppGallery Connect 发布证书与 Profile，完成 release 构建与稳定性自检。",
        "第 11 至 12 周：申请 AppGallery Connect 发布证书与 Profile，完成 release 构建与稳定性自检；提交应用市场，并按审核意见整改。":
        "第 10 至 11 周：在有真实手机的条件下安装验证一次；提交应用市场，并按审核意见整改。",
        "第 13 至 14 周：完成端侧调度实验，测量固定召回深度与自适应召回深度在延迟、内存、精确率上的差异，产出实验数据与图表。":
        "第 12 至 13 周：软著下证（预期，普通件 20 至 30 个工作日）；上架复检；"
        "并完成端侧调度实验，测量固定召回深度与自适应召回深度在延迟、内存、精确率上的差异。",
        "第 15 至 16 周：完成课程设计报告、结课答辩 PPT 与演示视频，进行上架复检与全部交付物的最终核对。":
        "第 14 至 16 周：完成课程设计报告、结课答辩 PPT 与演示视频，进行全部交付物的最终核对。",
    }
    hit = 0
    for p in doc.paragraphs:
        for old, new in reps.items():
            if p.text.strip() == old:
                for r in list(p.runs):
                    r.text = ""
                # 保留原样式：复用第一个 run 的格式
                run = p.add_run(new)
                run.font.name = "宋体"
                run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
                run.font.size = Pt(12)
                hit += 1
                print(f"    ✅ 替换进度段：{old[:26]}…")
    if hit == 0:
        print("    ⚠️ 进度段未匹配到（可能已被手工改过）")


def main():
    for fname, group in COURSES.items():
        f = D / fname
        if not f.exists():
            print(f"  [跳过] {fname} 不存在")
            continue
        print(f"\n[{fname}]")
        doc = Document(f)
        fix_cover(doc, group)
        if "移动应用开发" in fname:
            fix_mobile_schedule(doc)
        doc.save(f)
        print(f"    已保存（{f.stat().st_size:,} B）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
