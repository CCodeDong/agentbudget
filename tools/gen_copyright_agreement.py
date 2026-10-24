#!/usr/bin/env python3
"""
软著「合作开发协议」生成器。

WHY THIS DOCUMENT IS NEEDED
    软著登记里"开发方式"一旦选合作开发，就不只是多填几个名字：
    登记机构需要证据表明**全体作者对权利归属没有争议**。
    缺这份协议是合作开发最常见的退回原因之一。

    所以这份协议要解决三个问题：
      1. 这个软件确实是我们几个一起做出来的
      2. 每个人具体做了什么（不能只写"共同开发"）
      3. 权利怎么分、署名怎么排、以后怎么行使

WHAT I CANNOT KNOW
    各方分工我不知道，所以留了下划线占位符。
    **不要照着我猜的分工去填** —— 如实写，这份文件是要签字的。

USAGE
    python tools/gen_copyright_agreement.py
"""

import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "deliverables" / "软著申请"
SOFTWARE_NAME = "离线资料库软件"
VERSION = "V1.0"


def add_title(doc, text, size=18):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(16)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = True


def add_para(doc, text, size=11, indent=True, space_after=8, bold=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.5
    if indent:
        p.paragraph_format.first_line_indent = Pt(22)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.font.name = "宋体"
    r.bold = bold
    return p


def add_blank(doc, n=1):
    for _ in range(n):
        doc.add_paragraph()


def main():
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    for m in ("top_margin", "bottom_margin"):
        setattr(sec, m, Cm(2.54))
    for m in ("left_margin", "right_margin"):
        setattr(sec, m, Cm(3.0))

    add_title(doc, "合作开发协议书")

    add_para(doc, f"本协议由下列各方于 ______ 年 ____ 月 ____ 日签订，"
                  f"就共同开发「{SOFTWARE_NAME}{VERSION}」事宜达成一致。")

    # --- 甲方乙方丙方 ---
    add_para(doc, "甲方（第一作者）：", indent=False, bold=True, space_after=2)
    add_para(doc, "姓名：____________　　身份证号：______________________________", indent=False, space_after=2)
    add_para(doc, "通信地址：__________________________________　联系电话：______________", indent=False, space_after=2)
    add_para(doc, "工作单位（就读院校）：__________________________________", indent=False)

    add_para(doc, "乙方：", indent=False, bold=True, space_after=2)
    add_para(doc, "姓名：____________　　身份证号：______________________________", indent=False, space_after=2)
    add_para(doc, "通信地址：__________________________________　联系电话：______________", indent=False, space_after=2)
    add_para(doc, "工作单位（就读院校）：__________________________________", indent=False)

    add_para(doc, "丙方：", indent=False, bold=True, space_after=2)
    add_para(doc, "姓名：____________　　身份证号：______________________________", indent=False, space_after=2)
    add_para(doc, "通信地址：__________________________________　联系电话：______________", indent=False, space_after=2)
    add_para(doc, "工作单位（就读院校）：__________________________________", indent=False)

    add_para(doc, "（如合作方不足三人，删除多余的「丙方」部分；超过三人按同样格式增列。）",
             size=9, indent=False)

    # --- 第一条 ---
    add_para(doc, "第一条　合作开发的软件", indent=False, bold=True)
    add_para(doc, f"各方共同开发完成的软件名称为「{SOFTWARE_NAME}」，版本号为 {VERSION}，"
                  f"该软件为运行于 HarmonyOS 平台的个人资料管理与全文检索工具，"
                  f"具备资料导入、全文检索、检索深度自适应、决策解释、资料管理、"
                  f"文字识别、设备能力探测与设备内自测等功能。")

    # --- 第二条 ---
    add_para(doc, "第二条　各方分工", indent=False, bold=True)
    add_para(doc, "各方对本软件的实质性贡献如下（须如实填写，不得只写「共同开发」）：",
             indent=True)
    add_para(doc, "甲方：________________________________________________________________", indent=False, space_after=6)
    add_para(doc, "______________________________________________________________________", indent=False, space_after=10)
    add_para(doc, "乙方：________________________________________________________________", indent=False, space_after=6)
    add_para(doc, "______________________________________________________________________", indent=False, space_after=10)
    add_para(doc, "丙方：________________________________________________________________", indent=False, space_after=6)
    add_para(doc, "______________________________________________________________________", indent=False, space_after=10)
    add_para(doc, "填写建议：按「负责内容 + 涉及模块」的形式写，例如"
                  "「负责检索核心模块（切词、倒排索引、BM25 打分、自适应条数决策）」、"
                  "「负责 ArkTS 应用界面与流水线集成」、"
                  "「负责测试用例编写与真机验证」。",
             size=9, indent=True)

    # --- 第三条 ---
    add_para(doc, "第三条　著作权归属", indent=False, bold=True)
    add_para(doc, f"各方一致确认：「{SOFTWARE_NAME}{VERSION}」的计算机软件著作权由"
                  f"甲、乙、丙三方共同享有，属于合作作品，"
                  f"各方均为该软件的著作权人。")
    add_para(doc, "在办理计算机软件著作权登记时，登记的权利人为上述三方全体，"
                  "署名顺序为：第一作者（甲方）____________，"
                  "第二作者（乙方）____________，第三作者（丙方）____________。")
    add_para(doc, "各方确认上述署名顺序已协商一致，不存在争议。")

    # --- 第四条 ---
    add_para(doc, "第四条　著作权的行使", indent=False, bold=True)
    add_para(doc, "（一）各方均可为个人学习、研究、非商业性展示之目的自行使用本软件。")
    add_para(doc, "（二）对本软件进行转让、许可他人使用、发表、商业运营或办理著作权变更登记，"
                  "须经全体著作权人协商一致并书面确认。")
    add_para(doc, "（三）任何一方发现第三方侵犯本软件著作权时，应及时通知其他各方；"
                  "维权所得收益由各方协商分配。")

    # --- 第五条 ---
    add_para(doc, "第五条　声明与保证", indent=False, bold=True)
    add_para(doc, "各方共同声明并保证：")
    add_para(doc, "（一）本软件由各方独立开发完成，未抄袭、复制任何第三方的软件或代码；")
    add_para(doc, "（二）本软件不侵犯任何第三方的著作权、专利权、商标权或其他合法权益；")
    add_para(doc, "（三）本软件所使用的第三方开源组件均已遵守其许可协议"
                  "（如有，应在附录中列明）；")
    add_para(doc, "（四）本协议所述内容真实、准确，如因不实陈述导致登记被撤销，"
                  "由各方共同承担责任。")

    # --- 第六条 ---
    add_para(doc, "第六条　争议解决", indent=False, bold=True)
    add_para(doc, "因本协议引起的争议，各方应首先友好协商解决；"
                  "协商不成的，任何一方可向有管辖权的人民法院提起诉讼。")

    # --- 第七条 ---
    add_para(doc, "第七条　其他", indent=False, bold=True)
    add_para(doc, "本协议自各方签字之日起生效，一式 ____ 份，各方各执一份，具有同等法律效力。")
    add_para(doc, "本协议未尽事宜，各方可另行签订补充协议，补充协议与本协议具有同等效力。")

    # --- 签字 ---
    add_blank(doc, 1)
    add_para(doc, "甲方（签字）：________________________　　日期：______ 年 ____ 月 ____ 日",
             indent=False, space_after=16)
    add_para(doc, "乙方（签字）：________________________　　日期：______ 年 ____ 月 ____ 日",
             indent=False, space_after=16)
    add_para(doc, "丙方（签字）：________________________　　日期：______ 年 ____ 月 ____ 日",
             indent=False, space_after=16)

    add_blank(doc, 1)
    add_para(doc, "注：本协议需全体作者手写签字后扫描或拍照上传，"
                  "打印件上的姓名须与身份证一致。",
             size=9, indent=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "合作开发协议书（模板）.docx"
    doc.save(out)
    print("=" * 74)
    print("生成合作开发协议书模板")
    print("=" * 74)
    print(f"  已生成：{out}")
    print(f"  大小  ：{out.stat().st_size:,} B")
    print()
    print("  [!] 这是**模板**，有三处必须你亲手填写：")
    print("     1. 三个人的姓名、身份证号、联系方式、就读院校")
    print("     2. 第二条「各方分工」—— 如实写，不要照抄我的示例")
    print("     3. 第三条的署名顺序")
    print("  填好后打印、三个人手写签字、扫描或拍照上传。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
