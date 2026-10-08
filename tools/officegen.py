#!/usr/bin/env python3
"""
Generate the two courses' formal deliverables.

Two artifacts per course, as required by the course briefs:
  * a design report (.docx)
  * a defence deck (.pptx)

Everything here is distilled from the material already produced and verified in
docs/00..11, paper/01 and the seven experiment result sets. Nothing is invented
for the report: every number traces back to a recorded run or a build log.

Usage:
    python tools/make_deliverables.py
"""

import json
import statistics
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from pptx import Presentation
from pptx.dml.color import RGBColor as PRGB
from pptx.util import Inches, Pt as PPt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliverables"
EXP = ROOT / "experiments"

CN_BODY = "宋体"
CN_HEAD = "黑体"
EN_BODY = "Times New Roman"
EN_HEAD = "Arial"


# ---------------------------------------------------------------------------
# docx helpers
# ---------------------------------------------------------------------------

def _font(run, size=12, bold=False, name=EN_BODY, east=CN_BODY, color=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = rpr.makeelement(qn('w:rFonts'), {})
        rpr.append(rf)
    rf.set(qn('w:eastAsia'), east)
    if color:
        run.font.color.rgb = color


def new_doc(title, subtitle):
    doc = Document()
    st = doc.styles['Normal']
    st.font.name = EN_BODY
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), CN_BODY)
    for i, (nm, sz) in enumerate((('Heading 1', 16), ('Heading 2', 14), ('Heading 3', 13))):
        s = doc.styles[nm]
        s.font.name = EN_HEAD
        s.font.size = Pt(sz)
        s.font.color.rgb = RGBColor(0, 0, 0)
        s.element.rPr.rFonts.set(qn('w:eastAsia'), CN_HEAD)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p.add_run(title), size=22, bold=True, name=CN_HEAD, east=CN_HEAD)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p.add_run(subtitle), size=13, east=CN_BODY)
    doc.add_paragraph()
    return doc


def h(doc, text, level=1):
    doc.add_heading(text, level=level)


def para(doc, text, size=12, bold=False):
    p = doc.add_paragraph()
    _font(p.add_run(text), size=size, bold=bold)
    p.paragraph_format.first_line_indent = Cm(0.74) if not bold else Cm(0)
    return p


def bullets(doc, items, level=0):
    for it in items:
        p = doc.add_paragraph(style='List Bullet')
        if level:
            p.paragraph_format.left_indent = Cm(0.74 + 0.6 * level)
        _font(p.add_run(it), size=11.5)


def code_block(doc, text):
    for line in text.strip('\n').split('\n'):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.8)
        p.paragraph_format.space_after = Pt(0)
        _font(p.add_run(line), size=9.5, name='Consolas', east='Consolas')


def table(doc, headers, rows, caption=None):
    if caption:
        p = doc.add_paragraph()
        _font(p.add_run(caption), size=10.5, bold=True)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = 'Table Grid'
    for i, hd in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ''
        _font(cell.paragraphs[0].add_run(str(hd)), size=10.5, bold=True)
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = ''
            _font(cells[i].paragraphs[0].add_run(str(v)), size=10.5)
    doc.add_paragraph()
    return t


# ---------------------------------------------------------------------------
# pptx helpers
# ---------------------------------------------------------------------------

def new_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def _txbox(slide, left, top, width, height):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    return tf


def _set_font(run, size, bold=False, color=(0x1A, 0x1A, 0x1A)):
    run.font.size = PPt(size)
    run.font.bold = bold
    run.font.color.rgb = PRGB(*color)
    run.font.name = CN_BODY


def _add(p, text, size, bold=False, color=(0x1A, 0x1A, 0x1A)):
    """python-pptx's add_run() takes no arguments; text is assigned after."""
    r = p.add_run()
    r.text = text
    _set_font(r, size, bold, color)
    return r


def slide_title(prs, title, subtitle=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tf = _txbox(s, 0.6, 0.45, 12.1, 1.0)
    _add(tf.paragraphs[0], title, 30, True, (0x0A, 0x35, 0x82))
    if subtitle:
        tf2 = _txbox(s, 0.6, 1.35, 12.1, 0.6)
        _add(tf2.paragraphs[0], subtitle, 15, False, (0x60, 0x60, 0x60))
    return s


def slide_bullets(prs, title, items, notes=None, subtitle=None):
    s = slide_title(prs, title, subtitle)
    tf = _txbox(s, 0.7, 2.0, 11.9, 5.0)
    first = True
    for it in items:
        lvl = 0
        text = it
        if isinstance(it, tuple):
            text, lvl = it
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = lvl
        prefix = '▪ ' if lvl == 0 else '– '
        _add(p, prefix + text, 17 if lvl == 0 else 14.5,
             lvl == 0, (0x1A, 0x1A, 0x1A) if lvl == 0 else (0x44, 0x44, 0x44))
        p.space_after = PPt(8)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def slide_table(prs, title, headers, rows, notes=None, subtitle=None):
    s = slide_title(prs, title, subtitle)
    shp = s.shapes.add_table(len(rows) + 1, len(headers),
                             Inches(0.7), Inches(2.0), Inches(11.9), Inches(0.5 * (len(rows) + 1)))
    tbl = shp.table
    for i, hd in enumerate(headers):
        c = tbl.cell(0, i)
        c.text = ''
        _add(c.text_frame.paragraphs[0], str(hd), 13, True, (0xFF, 0xFF, 0xFF))
        c.fill.solid()
        c.fill.fore_color.rgb = PRGB(0x0A, 0x35, 0x82)
    for r, row in enumerate(rows, start=1):
        for i, v in enumerate(row):
            c = tbl.cell(r, i)
            c.text = ''
            _add(c.text_frame.paragraphs[0], str(v), 12)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def slide_code(prs, title, code, notes=None):
    s = slide_title(prs, title)
    tf = _txbox(s, 0.7, 2.0, 11.9, 5.0)
    first = True
    for line in code.strip('\n').split('\n'):
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        r = p.add_run()
        r.text = line
        r.font.size = PPt(13)
        r.font.name = 'Consolas'
        r.font.color.rgb = PRGB(0x1A, 0x1A, 0x1A)
        p.space_after = PPt(2)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def slide_section(prs, text):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tf = _txbox(s, 1.2, 2.9, 11.0, 1.6)
    _add(tf.paragraphs[0], text, 40, True, (0x0A, 0x35, 0x82))
    return s


# ---------------------------------------------------------------------------
# Verified facts, read from the recorded runs so the decks cannot drift
# ---------------------------------------------------------------------------

def load_summary(name):
    f = EXP / name / "summary.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


def summarise(name, key_field):
    rows = load_summary(name)
    out = {}
    for r in rows:
        out[(r["mode"], r.get(key_field))] = r
    return out


KSWEEP = load_summary("results_ksweep")
MULTITURN = load_summary("results_multiturn")
POOL15 = load_summary("results_pool15_fixed")
POOL5 = load_summary("results")
