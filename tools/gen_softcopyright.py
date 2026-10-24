#!/usr/bin/env python3
"""
软著登记材料生成器 —— 源代码文档与软件说明书。

WHY A GENERATOR INSTEAD OF HAND-MADE DOCX
    软著对源代码文档的格式要求很具体：
      · 每页 50 行
      · 页眉写软件名称 + 版本号
      · 连续页码
    手搓一遍容易出错，而且**代码一改就得重来**。
    用脚本生成的好处是：任何时候都能一条命令重新导出，
    并且可以断言"导出的是当前实际构建的那份代码"。

TWO DOCUMENTS
    1. 源代码文档  —— 前 30 页 + 后 30 页，不足 60 页则提交全部
       我们的唯一源码是 2,344 行（去空行）≈ 47 页 < 60 页 -> 提交全部

    2. 软件说明书  —— 有结构的说明文档，不是截图堆砌

SYNC CHECK（这个才是最容易出问题的地方）
    `app/offlinelib/entry/src/main/ets/lib/*.ts` 是
    `projects/offlinelib-core/src/*.ts` 的手工副本。
    两者一旦不一致，登记的代码就不是实际运行的代码。
    所以生成前先做 SHA256 比对，不一致直接拒绝生成。

USAGE
    python tools/gen_softcopyright.py check     # 只做一致性检查
    python tools/gen_softcopyright.py source    # 生成源代码文档
    python tools/gen_softcopyright.py manual    # 生成说明书
    python tools/gen_softcopyright.py all
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "deliverables" / "软著申请"

SOFTWARE_NAME = "离线资料库软件"
VERSION = "V1.0"
HEADER_TEXT = f"{SOFTWARE_NAME} {VERSION}"

# 每页行数与软换行宽度。
# 105 字符在 8pt Consolas + A4 左右边距 2cm 下不会换行（最长原始行 115 字符，
# 会在代码里被软换行到 105 以内，因此每个"逻辑行"恰好占一个物理行）。
LINES_PER_PAGE = 50
WRAP_WIDTH = 105
FONT_SIZE_PT = 8

# 源代码编排顺序：从底层到上层，让审查员能看出架构
SOURCE_FILES = [
    ("projects/offlinelib-core/src/types.ts", "数据结构定义"),
    ("projects/offlinelib-core/src/tokenize.ts", "中文单字与二元组切词"),
    ("projects/offlinelib-core/src/index.ts", "倒排索引与 BM25 打分"),
    ("projects/offlinelib-core/src/search.ts", "检索流程与自适应 k"),
    ("projects/offlinelib-core/src/store.ts", "文档存储与持久化"),
    ("projects/offlinelib-core/src/ocr.ts", "OCR 抽象层与质量判定"),
    ("projects/offlinelib-core/src/pipeline.ts", "库服务流水线编排"),
    ("app/offlinelib/entry/src/main/ets/lib/realocr.ets", "真实 OCR 实现（CoreVisionKit）"),
    ("app/offlinelib/entry/src/main/ets/pages/Index.ets", "主界面"),
    ("app/offlinelib/entry/src/main/ets/selfcheck/Capability.ets", "设备能力探测"),
    ("app/offlinelib/entry/src/main/ets/selfcheck/SelfCheck.ets", "设备内自测"),
    ("app/offlinelib/entry/src/main/ets/entryability/EntryAbility.ets", "应用入口"),
]

# 需要做同步校验的配对：(核心源, 应用内副本)
SYNC_PAIRS = [
    ("types.ts", "types.ts"), ("tokenize.ts", "tokenize.ts"),
    ("index.ts", "index.ts"), ("search.ts", "search.ts"),
    ("store.ts", "store.ts"), ("ocr.ts", "ocr.ts"),
    ("pipeline.ts", "pipeline.ts"),
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_sync() -> bool:
    print("=" * 74)
    print("同步校验：核心源码 vs 应用内副本")
    print("=" * 74)
    ok = True
    core = ROOT / "projects" / "offlinelib-core" / "src"
    copy = ROOT / "app" / "offlinelib" / "entry" / "src" / "main" / "ets" / "lib"
    for a, b in SYNC_PAIRS:
        pa, pb = core / a, copy / b
        if not pa.exists() or not pb.exists():
            print(f"  [缺失] {a}")
            ok = False
            continue
        same = sha256(pa) == sha256(pb)
        print(f"  {'[一致]' if same else '[不一致]'} {a}")
        if not same:
            ok = False
            print(f"       {pa}")
            print(f"       {pb}")
    print()
    if not ok:
        print("  [!] 副本与核心不一致 —— 登记的将不是实际运行的代码。")
        print("     先同步：把 projects/offlinelib-core/src/*.ts 复制到 ets/lib/")
    else:
        print("  全部一致，可以生成文档。")
    return ok


def read_lines(rel: str) -> list:
    """读文件并去掉空行。软著要求源代码文档不含空行。"""
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if line == "":
            continue
        out.append(line)
    return out


def wrap_line(line: str) -> list:
    """把超过 WRAP_WIDTH 的行软换行，保证一行占一个物理行。"""
    if len(line) <= WRAP_WIDTH:
        return [line]
    # 续行缩进：比原始缩进多 4 格，但不超过 20 格，
    # 否则可用宽度会被压缩到很小、产生过多续行。
    indent = len(line) - len(line.lstrip())
    pad = " " * min(indent + 4, 20)
    if len(pad) >= WRAP_WIDTH - 10:
        pad = " " * 4

    out = [line[:WRAP_WIDTH]]
    rest = line[WRAP_WIDTH:]
    avail = WRAP_WIDTH - len(pad)
    while rest:
        out.append(pad + rest[:avail])
        rest = rest[avail:]
    return out


def build_source_lines() -> list:
    """拼出完整源代码行序列，含文件分隔注释。

    [!] 刻意**不插入空行**。
       软著要求源代码文档"不含空行"，而且空行会让人怀疑是在凑页数。
       文件之间的分隔由 4 行注释块承担，视觉上已经足够清楚。
       源码里的空行也已在 read_lines() 里去掉了。
    """
    lines = []
    for i, (rel, desc) in enumerate(SOURCE_FILES):
        lines.append("/* " + "=" * 68 + " */")
        lines.append(f"/* 文件 {i + 1}/{len(SOURCE_FILES)}：{rel} */")
        lines.append(f"/* 作用：{desc} */")
        lines.append("/* " + "=" * 68 + " */")
        for raw in read_lines(rel):
            lines.extend(wrap_line(raw))
    return lines


def add_page_number_footer(section):
    """在页脚插入「第 N 页」域。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = 1  # center
    run = p.add_run("第 ")
    run.font.size = docx_pt(9)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    r = p.add_run()
    r._r.append(fld_begin)
    r._r.append(instr)
    r._r.append(fld_end)
    r2 = p.add_run(" 页")
    r2.font.size = docx_pt(9)


def docx_pt(n):
    from docx.shared import Pt
    return Pt(n)


def gen_source():
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK

    ok = check_sync()
    if not ok:
        print("\n  拒绝生成：先解决上面的不一致。")
        return 1

    lines = build_source_lines()
    pages = (len(lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE
    print("=" * 74)
    print("生成源代码文档")
    print("=" * 74)
    print(f"  逻辑行数 : {len(lines)}")
    print(f"  每页行数 : {LINES_PER_PAGE}")
    print(f"  总页数   : {pages}")
    if pages <= 60:
        print("  规则     : 不足 60 页 -> **提交全部源代码**")
    else:
        print("  规则     : 超过 60 页 -> 提交前 30 页 + 后 30 页")

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(1.8)
    sec.left_margin = Cm(2.0)
    sec.right_margin = Cm(2.0)

    # 页眉
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run(HEADER_TEXT)
    hr.font.size = Pt(9)
    hr.font.name = "宋体"

    add_page_number_footer(sec)

    # 正文样式：紧凑、等宽
    style = doc.styles["Normal"]
    style.font.name = "Consolas"
    style.font.size = Pt(FONT_SIZE_PT)
    pf = style.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0

    for idx, line in enumerate(lines):
        if idx % LINES_PER_PAGE == 0 and idx > 0:
            # 在上一段末尾插入分页符
            doc.paragraphs[-1].runs[-1].add_break(WD_BREAK.PAGE)
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        run = p.add_run(line if line else " ")
        run.font.name = "Consolas"
        run.font.size = Pt(FONT_SIZE_PT)
        # 中文字符也走同一字体
        rpr = run._element.get_or_add_rPr()
        from docx.oxml.ns import qn
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            from docx.oxml import OxmlElement
            rf = OxmlElement("w:rFonts")
            rpr.append(rf)
        rf.set(qn("w:eastAsia"), "宋体")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"源代码文档-{SOFTWARE_NAME}{VERSION}.docx"
    doc.save(out)
    print(f"\n  已生成：{out}")
    print(f"  大小  ：{out.stat().st_size:,} B")

    # 同时导出一份纯文本，方便自查行数与页数
    txt = OUT_DIR / f"源代码文档-{SOFTWARE_NAME}{VERSION}.txt"
    txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"  纯文本：{txt.name}（用于核对行数）")
    return 0


def gen_manual():
    from docx import Document
    from docx.shared import Cm, Pt

    print("=" * 74)
    print("生成软件说明书")
    print("=" * 74)

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    for m in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sec, m, Cm(2.4))

    # 封面
    for _ in range(6):
        doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = 1
    r = t.add_run(f"{SOFTWARE_NAME}")
    r.font.size = Pt(26)
    r.bold = True
    t2 = doc.add_paragraph()
    t2.alignment = 1
    r2 = t2.add_run("软件说明书")
    r2.font.size = Pt(20)
    doc.add_paragraph()
    t3 = doc.add_paragraph()
    t3.alignment = 1
    r3 = t3.add_run(f"版本号：{VERSION}")
    r3.font.size = Pt(14)
    for _ in range(10):
        doc.add_paragraph()
    t4 = doc.add_paragraph()
    t4.alignment = 1
    t4.add_run("二〇二六年十月").font.size = Pt(12)
    doc.add_page_break()

    def h1(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(text)
        r.font.size = Pt(15)
        r.bold = True

    def h2(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(text)
        r.font.size = Pt(12.5)
        r.bold = True

    def para(text, size=10.5):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.4
        p.add_run(text).font.size = Pt(size)
        return p

    def bullet(text, size=10.5):
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        p.add_run(text).font.size = Pt(size)

    # 一、软件概述
    h1("一、软件概述")
    para("离线资料库软件是一款运行于 HarmonyOS 终端的个人资料管理与全文检索工具。"
         "用户可以把笔记、讲义、摘录等文字内容存入本机资料库，之后用关键词快速找回，"
         "并直接看到命中位置在原文中的高亮。")
    para("软件的核心设计目标是「完全离线」：不申请任何网络权限，不发起任何网络请求，"
         "全部索引与检索都在设备本地完成。这一约束不是事后补充，而是从第一行代码起就作为前提。")
    h2("1.1 目标用户")
    bullet("需要在手机上随时查阅自己积累的资料的学生与研究者")
    bullet("对隐私敏感、不愿把笔记上传到云端的用户")
    bullet("网络条件受限（地铁、飞机、会场）时需要检索资料的用户")
    h2("1.2 主要解决的问题")
    para("手机上的资料分散在备忘录、聊天记录、截图、PDF 中，找起来靠记忆和翻找。"
         "系统自带的搜索往往只匹配标题或文件名，不进入正文。"
         "本软件把正文切成片段并建立倒排索引，使得「我记得好像在哪写过这个词」能够被检索到。")

    # 二、运行环境
    h1("二、运行环境")
    h2("2.1 硬件环境")
    bullet("设备形态：手机、平板、个人计算机（2in1）")
    bullet("内存：建议 4 GB 及以上")
    bullet("存储：软件本体约 1 MB，资料占用取决于用户导入的内容量")
    h2("2.2 软件环境")
    bullet("操作系统：HarmonyOS NEXT")
    bullet("编译 SDK：HarmonyOS SDK API 12 及以上")
    bullet("已验证运行环境：MateBook Pro（HAD-W32，2in1 形态，API 23）")
    h2("2.3 权限说明")
    para("本软件不申请任何系统权限，包括网络权限。安装后可通过系统的应用信息页面确认"
         "其权限列表为空。这是「数据不出设备」这一主张在权限层面的直接体现。")

    # 三、主要功能
    h1("三、主要功能")
    h2("3.1 资料导入")
    para("在「资料」页输入标题与正文，点击「加入资料库」即完成入库。"
         "导入时软件会自动把长文本切分成便于检索的片段，并为每个片段建立索引。")
    h2("3.2 全文检索")
    para("在「搜索」页输入关键词，软件按 BM25 算法对全部片段打分并排序返回结果。"
         "命中的关键词在结果中以红色加粗高亮显示，便于快速判断相关性。")
    h2("3.3 检索深度自适应")
    para("软件默认采用「按得分分布自适应」的检索深度策略：根据候选结果的得分是否出现"
         "明显断层，自动决定返回几条结果，而不是固定返回若干条。"
         "用户也可以切换到「固定 3 条」模式作对照。")
    para("这是本软件区别于一般检索工具的关键设计：返回条数由内容本身的区分度决定，"
         "而不是由一个人为设定的常数决定。")
    h2("3.4 决策解释")
    para("每次检索后，界面会显示本次决策的依据，包括：实际返回条数、深度来源"
         "（自适应还是固定）、受限因素（时间/内存/电量）、候选数量。"
         "用户因此可以理解「为什么给我这几条」，而不是面对一个黑箱。")
    h2("3.5 资料管理与增量删除")
    para("「资料」页列出全部已入库文档，显示来源与字数，并支持逐条删除。"
         "删除采用增量方式：只标记失效片段并在比例超限时自动整理，"
         "不需要重建整个索引。")
    h2("3.6 图片导入与文字识别")
    para("软件集成了系统的 CoreVisionKit 文字识别能力。用户在「资料」页点击「从相册选图识别」，"
         "由系统相册界面选择一张图片后，软件自动识别其中的文字，"
         "并将结果填入标题与正文输入框，用户确认无误后点击「加入资料库」完成入库。")
    para("识别结果会附带一个质量分档，用于决定「直接收下 / 提示重拍 / 丢弃」。")
    para("图片来源采用系统相册选择器而非直接调用相机，原因是："
         "调用相机需要申请相机权限，而本软件的设计前提是不申请任何系统权限。"
         "系统相册选择器由系统界面完成取图，应用仅获得用户选定的那一张图片，"
         "无需任何权限即可实现图片导入。这是功能与隐私之间的自觉取舍。")
    para("需要说明的是：文字识别引擎本身不返回标量置信度，仅有文本块信息，"
         "因此质量分档由本软件根据块数与文本长度估计，属于经验性判断。")
    h2("3.7 设备能力探测")
    para("「高级」页提供设备能力探测功能，用系统的能力查询接口列出文字识别、端侧检索、"
         "视觉基础、智能体框架等能力在当前设备上是否可用。"
         "这一功能的价值在于：软件可以据此决定启用哪些特性，而不是在调用失败时崩溃。")
    h2("3.8 设备内自测")
    para("「高级」页提供设备内自测功能，在设备上直接运行 14 项检查并逐条显示结果，"
         "覆盖切词、分块、打分、排序、高亮、存储往返、文字识别判定与流水线全流程。"
         "自测全部通过时会显示「全部通过：14 / 14」。")

    # 四、技术特点
    h1("四、技术特点")
    h2("4.1 中文切词不依赖词典")
    para("中文检索的常见做法是引入分词词典，但词典会带来体积、维护与未登录词三类问题。"
         "本软件采用「单字 + 二元组」的切词方式：既产生单字索引保证召回，"
         "又产生相邻两字的组合保证区分度，完全不需要词典。")
    h2("4.2 BM25 排序")
    para("打分采用 BM25 算法，参数取 k1 = 1.5、b = 0.75。"
         "该算法同时考虑词频饱和与文档长度归一化，避免长文档因为「字多」而获得不当优势。")
    h2("4.3 墓碑式增量删除")
    para("删除文档时不为每个片段重排索引，而是把片段标记为失效（墓碑）。"
         "当墓碑占比超过 20% 时自动整理一次。相比每次删除都全量重建，"
         "这一策略把删除开销从「与库规模成正比」降为「与删除量成正比」。")
    h2("4.4 索引与持久化分离")
    para("持久化只保存原始文档，索引在启动时重建。"
         "这样索引格式变化不会导致旧存档失效，而重建在常见规模下是秒级操作。")
    h2("4.5 文字识别做成接口而非直接依赖")
    para("文字识别能力被定义为接口，真实实现由上层注入。"
         "这样在没有该能力的设备上软件仍可正常启动并使用其余功能，"
         "而不是因为依赖缺失而无法运行。")

    # 五、操作流程
    h1("五、操作流程")
    h2("5.1 首次使用")
    para("启动软件后默认进入「搜索」页。首次启动会自动放入一份示例资料，"
         "用户可以直接搜索示例内容以了解软件行为。")
    h2("5.2 导入自己的资料")
    para("① 切换到底部「资料」页；② 在标题框填写标题（可留空）；"
         "③ 在正文框粘贴或输入内容；④ 点击「加入资料库」。"
         "导入成功后页面顶部的统计数字会更新。")
    h2("5.3 检索")
    para("① 切回「搜索」页；② 输入关键词；③ 点击「搜索」或按回车。"
         "结果按相关度排序，关键词高亮显示。页面顶部会显示本次决策的依据。")
    h2("5.4 切换检索深度")
    para("在「搜索」页打开或关闭「检索深度」开关即可在自适应与固定 3 条之间切换。"
         "切换后需要重新搜索才会生效。")
    h2("5.5 运行自测")
    para("切换到「高级」页，点击「运行设备内自测」，稍候即可看到 14 项检查的逐条结果。"
         "每一项前面显示对勾表示通过，叉号表示未通过并给出原因。")

    # 六、数据结构与模块说明
    h1("六、数据结构与模块说明")
    h2("6.1 主要数据结构")
    bullet("文档（DocItem）：标识、标题、来源类型、原始位置、加入时间、正文")
    bullet("片段（Chunk）：所属文档、序号、正文起止位置、片段文本")
    bullet("命中（Hit）：命中的片段、相关度得分、命中词及其出现次数、高亮区间")
    bullet("搜索选项（SearchOptions）：固定条数、最少条数、最多条数")
    bullet("资源预算（BudgetInput）：时间预算、内存预算、电量百分比")
    h2("6.2 模块划分")
    bullet("切词模块：把文本转换为检索词序列")
    bullet("索引模块：倒排表维护、BM25 打分、片段切分、命中定位")
    bullet("检索模块：诊断、自适应条数决策、资源预算决策、结果组装")
    bullet("存储模块：文档集合的增删改查与序列化")
    bullet("识别模块：识别引擎接口、质量分档策略、真实引擎实现")
    bullet("流水线模块：把上述模块组合成对界面友好的服务接口")

    # 七、已验证情况
    h1("七、已验证情况")
    para("为避免夸大，此处只陈述实际做过的验证：")
    bullet("核心算法：87 项单元测试在开发机上全部通过")
    bullet("真实语料：以 64 份文档（约 44 万字）为语料，150 条已知答案查询的召回率为 100%")
    bullet("编译兼容：通过 HarmonyOS ArkTS 编译器编译，无错误")
    bullet("真机运行：在 MateBook Pro（2in1 形态，API 23）上安装、启动、运行正常")
    bullet("设备内自测：14 项检查在该真机上全部通过")
    bullet("真实文字识别：内置测试图识别成功，输出 181 字，耗时 222 毫秒")
    para("尚未验证的部分：相机拍照路径、手写体与低质量图片的识别效果、"
         "手机形态设备上的表现。这些限制在技术文档中有明确记录。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"软件说明书-{SOFTWARE_NAME}{VERSION}.docx"
    doc.save(out)
    print(f"  已生成：{out}")
    print(f"  大小  ：{out.stat().st_size:,} B")
    return 0


def gen_pdf():
    """
    直出 PDF。

    WHY 直接生成 PDF 而不是把 docx 转过去
        本机没有 Word / WPS / LibreOffice，转不了。
        而且很多登记系统只收 PDF —— 直接生成反而更可控：
        **每一页放多少行由代码决定，不依赖任何排版引擎的换行行为。**

    字体选择
        用微软雅黑（msyh.ttc）。它同时含拉丁与中文，省去在同一行里切换字体。
        代价是拉丁字符不是等宽 —— 所以绘制前先用 stringWidth 实测最宽的行，
        必要时自动缩小字号，保证不换行。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    ok = check_sync()
    if not ok:
        print("\n  拒绝生成：先解决上面的不一致。")
        return 1

    lines = build_source_lines()
    pages = (len(lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE

    # 注册字体
    font_path = None
    for cand in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                 r"C:\Windows\Fonts\simsun.ttc"):
        if Path(cand).exists():
            font_path = cand
            break
    if font_path is None:
        print("  找不到中文字体，无法生成 PDF")
        return 2
    pdfmetrics.registerFont(TTFont("CJK", font_path, subfontIndex=0))

    W, H = A4
    margin_lr = 56.7      # 2cm
    margin_top = 70.0
    margin_bottom = 60.0
    avail_w = W - 2 * margin_lr
    avail_h = H - margin_top - margin_bottom
    line_h = avail_h / LINES_PER_PAGE

    # 实测最宽行，必要时缩小字号
    size = FONT_SIZE_PT
    while size > 5.0:
        widest = max(pdfmetrics.stringWidth(ln or " ", "CJK", size) for ln in lines)
        if widest <= avail_w - 4:
            break
        size -= 0.25

    print("=" * 74)
    print("生成源代码文档 PDF")
    print("=" * 74)
    print(f"  逻辑行数 : {len(lines)}")
    print(f"  每页行数 : {LINES_PER_PAGE}")
    print(f"  总页数   : {pages}")
    print(f"  字体     : {Path(font_path).name}")
    print(f"  字号     : {size} pt（自动适配，可用宽 {avail_w:.0f} pt）")
    print(f"  行高     : {line_h:.2f} pt")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"源代码文档-{SOFTWARE_NAME}{VERSION}.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setTitle(f"{HEADER_TEXT} 源程序")
    c.setAuthor("西安交通大学")

    for page_no in range(pages):
        chunk = lines[page_no * LINES_PER_PAGE:(page_no + 1) * LINES_PER_PAGE]

        # 页眉
        c.setFont("CJK", 9)
        c.drawCentredString(W / 2, H - 42, HEADER_TEXT)
        # 页脚
        c.setFont("CJK", 9)
        c.drawCentredString(W / 2, 32, f"第 {page_no + 1} 页")

        # 正文
        c.setFont("CJK", size)
        y = H - margin_top
        for ln in chunk:
            c.drawString(margin_lr, y, ln if ln else " ")
            y -= line_h
        c.showPage()

    c.save()
    print(f"\n  已生成：{out}")
    print(f"  大小  ：{out.stat().st_size:,} B")

    # 用 pypdf 核对实际页数
    try:
        from pypdf import PdfReader
        real = len(PdfReader(str(out)).pages)
        print(f"  核对  ：PDF 实际 {real} 页 —— {'与预期一致' if real == pages else '不一致！'}")
    except Exception as e:
        print(f"  核对  ：跳过（{e}）")
    return 0


def gen_manual_pdf():
    """
    把说明书 docx 渲染成 PDF。

    WHY 从 docx 渲染而不是重复写一份内容
        两处维护同一份文字，早晚会不一致。
        源程序文档那边已经出现过"副本与核心不一致"的教训
        （app/.../lib/*.ts 是 projects/offlinelib-core/src/*.ts 的手工副本）。
        所以这里让 docx 成为**唯一内容源**，PDF 只是它的渲染结果。
    """
    from docx import Document
    from docx.oxml.ns import qn
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, ListFlowable,
                                    ListItem, PageBreak, PageTemplate, Paragraph,
                                    Spacer)

    src = OUT_DIR / f"软件说明书-{SOFTWARE_NAME}{VERSION}.docx"
    if not src.exists():
        print(f"  找不到 {src.name}，请先运行 manual")
        return 2

    font_path = r"C:\Windows\Fonts\msyh.ttc"
    if not Path(font_path).exists():
        print("  找不到中文字体")
        return 2
    pdfmetrics.registerFont(TTFont("CJK", font_path, subfontIndex=0))

    print("=" * 74)
    print("生成软件说明书 PDF")
    print("=" * 74)

    # 只用 docx 里实际用到的几种字号来判定层级
    doc = Document(str(src))
    blocks = []
    for p in doc.paragraphs:
        text = p.text.strip()
        has_break = any(b.get(qn("w:type")) == "page"
                        for b in p._p.findall(".//" + qn("w:br")))
        if not text:
            if has_break:
                blocks.append(("break", ""))
            continue
        size = None
        bold = False
        for r in p.runs:
            if r.font.size:
                size = r.font.size.pt
            if r.bold:
                bold = True
        style = p.style.name or ""
        if "List Bullet" in style:
            kind = "bullet"
        elif size and size >= 20:
            kind = "title"
        elif size and size >= 14:
            kind = "h1"
        elif size and size >= 12:
            kind = "h2"
        else:
            kind = "body"
        blocks.append((kind, text))
        if has_break:
            blocks.append(("break", ""))

    S = {
        "title": ParagraphStyle("t", fontName="CJK", fontSize=26, leading=36,
                                alignment=TA_CENTER, spaceAfter=10),
        "h1": ParagraphStyle("h1", fontName="CJK", fontSize=15, leading=22,
                             spaceBefore=14, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName="CJK", fontSize=12.5, leading=19,
                             spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("b", fontName="CJK", fontSize=10.5, leading=17,
                               spaceAfter=6),
        "bullet": ParagraphStyle("bl", fontName="CJK", fontSize=10.5, leading=16),
    }

    story = []
    pending_bullets = []

    def flush_bullets():
        if pending_bullets:
            story.append(ListFlowable(
                [ListItem(Paragraph(b, S["bullet"]), leftIndent=14)
                 for b in pending_bullets],
                bulletType="bullet", start="•", leftIndent=16,
                bulletFontName="CJK", bulletFontSize=10))
            story.append(Spacer(1, 4))
            pending_bullets.clear()

    for kind, text in blocks:
        if kind != "bullet":
            flush_bullets()
        if kind == "break":
            story.append(PageBreak())
        elif kind == "title":
            story.append(Spacer(1, 120))
            story.append(Paragraph(text, S["title"]))
        elif kind == "h1":
            story.append(Paragraph(text, S["h1"]))
        elif kind == "h2":
            story.append(Paragraph(text, S["h2"]))
        elif kind == "bullet":
            pending_bullets.append(text)
        else:
            story.append(Paragraph(text, S["body"]))
    flush_bullets()

    out = OUT_DIR / f"软件说明书-{SOFTWARE_NAME}{VERSION}.pdf"

    def on_page(canv, d):
        canv.setFont("CJK", 9)
        canv.drawCentredString(A4[0] / 2, 1.4 * cm, f"第 {canv.getPageNumber()} 页")

    docpdf = BaseDocTemplate(str(out), pagesize=A4,
                             leftMargin=2.4 * cm, rightMargin=2.4 * cm,
                             topMargin=2.4 * cm, bottomMargin=2.4 * cm)
    frame = Frame(docpdf.leftMargin, docpdf.bottomMargin,
                  docpdf.width, docpdf.height, id="f")
    docpdf.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=on_page)])
    docpdf.build(story)

    print(f"  已生成：{out}")
    print(f"  大小  ：{out.stat().st_size:,} B")
    try:
        from pypdf import PdfReader
        print(f"  页数  ：{len(PdfReader(str(out)).pages)}")
    except Exception as e:
        print(f"  页数  ：无法核对（{e}）")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        return 0 if check_sync() else 1
    if cmd == "source":
        return gen_source()
    if cmd == "manual":
        return gen_manual()
    if cmd == "manualpdf":
        return gen_manual_pdf()
    if cmd == "pdf":
        return gen_pdf()
    if cmd == "all":
        rc = gen_source()
        if rc != 0:
            return rc
        print()
        return gen_manual()
    if cmd == "everything":
        rc = gen_source()
        if rc != 0:
            return rc
        print()
        rc = gen_manual()
        if rc != 0:
            return rc
        print()
        return gen_pdf()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
