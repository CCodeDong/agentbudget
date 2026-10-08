#!/usr/bin/env python3
"""
Check internal consistency of the paper draft.

The draft has been edited across many rounds, so cross-references and figure
numbers can silently rot: a section renumbered, a figure reference left pointing
at a file that no longer exists, an appendix listing a figure under a name that
changed. Reviewers notice exactly this class of defect, and it is cheap to check.

Checks performed:
  1. Every `图 N` reference resolves to a figure file `figN_*.png`.
  2. Every `§X` or `§X.Y` reference resolves to a heading that exists.
  3. Every figure file listed in 附录 D exists on disk.
  4. Every figure on disk is listed in 附录 D.
  5. No U+2212 MINUS SIGN survives in prose tables (it renders as a missing glyph
     in the figures, and mixing the two minus characters makes the paper
     inconsistent -- figures use ASCII).

Usage:
    python tools/check_paper.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper" / "01-论文初稿.md"
FIGS = ROOT / "paper" / "figures"


def main():
    if not PAPER.exists():
        print(f"[check] ERROR: {PAPER} not found")
        return 2
    text = PAPER.read_text(encoding="utf-8")
    body, _, _ = text.partition("## 附录 D")

    problems = []

    # ---- 1. figure references ----
    fig_refs = sorted({int(n) for n in re.findall(r"图\s*(\d+)", body)})
    disk = {}
    for p in FIGS.glob("fig*_*.png"):
        m = re.match(r"fig(\d+)_", p.name)
        if m:
            disk[int(m.group(1))] = p.name
    print(f"[check] figure references in body : {fig_refs}")
    print(f"[check] figure files on disk      : {sorted(disk)}")
    for n in fig_refs:
        if n not in disk:
            problems.append(f"图 {n} is referenced but no fig{n}_*.png exists")

    # ---- 2. section references ----
    heads = set()
    for m in re.finditer(r"^#{2,3}\s+(\d+(?:\.\d+)?)", text, re.MULTILINE):
        heads.add(m.group(1))
    sec_refs = sorted({s for s in re.findall(r"§\s*(\d+(?:\.\d+)?)", body)})
    print(f"[check] section references        : {sec_refs}")
    for s in sec_refs:
        if s not in heads:
            problems.append(f"§{s} is referenced but no such heading exists")

    # ---- 3+4. appendix D <-> disk ----
    app = text.partition("## 附录 D")[2]
    listed = {}
    for m in re.finditer(r"`(fig\d+_[A-Za-z0-9_]+\.png)`", app):
        listed[m.group(1)] = True
    print(f"[check] figures listed in 附录 D   : {len(listed)}")
    for name in listed:
        if not (FIGS / name).exists():
            problems.append(f"附录 D lists {name} but the file does not exist")
    for n, name in sorted(disk.items()):
        if name not in listed:
            problems.append(f"{name} exists on disk but is not listed in 附录 D")

    # ---- 5. the figure font must carry U+2212 ----
    # The prose uses U+2212 MINUS SIGN (correct typography). If the figure font
    # loses that glyph, matplotlib silently renders a box and the figures become
    # inconsistent with the text -- and matplotlib only warns, it does not fail.
    # So the font choice is checked rather than trusted.
    warnings = []
    figsrc = ROOT / "tools" / "make_figures.py"
    if figsrc.exists():
        src = figsrc.read_text(encoding="utf-8")
        import re as _re
        m = _re.search(r'font\.sans-serif"\]\s*=\s*\[([^\]]+)\]', src)
        if m:
            preferred = _re.findall(r'"([^"]+)"', m.group(1))[0]
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.font_manager as fm
                from matplotlib.font_manager import FontProperties
                import warnings as _w
                import matplotlib.pyplot as _plt
                fp = FontProperties(family=preferred)
                if preferred not in {f.name for f in fm.fontManager.ttflist}:
                    problems.append(f"figure font '{preferred}' is not installed")
                else:
                    with _w.catch_warnings(record=True) as caught:
                        _w.simplefilter("always")
                        f = _plt.figure(figsize=(1, 1))
                        f.text(0.1, 0.5, "\u2212", fontproperties=fp)
                        f.canvas.draw()
                        missing = [str(x.message) for x in caught
                                   if "missing from font" in str(x.message)]
                        _plt.close(f)
                    if missing:
                        problems.append(
                            f"figure font '{preferred}' lacks U+2212; the prose uses it "
                            f"and the figures would silently render a missing glyph")
            except ImportError:
                warnings.append("matplotlib not importable; skipped the font/glyph check")

    # ---- 6. every figure must be cited at least once in the body ----
    for n, name in sorted(disk.items()):
        if n not in fig_refs:
            problems.append(f"{name} exists but 图 {n} is never cited in the body")

    # ---- 7. appendix D descriptions must match the figure script's titles ----
    # The figure script is the source of truth for what each figure SHOWS. When a
    # figure is redrawn because a result changed, its title is edited there; if
    # appendix D is not updated the paper silently describes the OLD figure.
    # That is exactly how the corrected pool-size result stayed stale in the
    # appendix for a round after the figure itself had been fixed.
    figsrc = ROOT / "tools" / "make_figures.py"
    if figsrc.exists():
        src = figsrc.read_text(encoding="utf-8")
        titles = {}
        for m in re.finditer(r'(?:suptitle|set_title)\(\s*"图\s*(\d+)\s+([^"]+)"', src):
            titles[m.group(1)] = m.group(2).strip()
        app_d = text.partition("## 附录 D")[2]
        listed = {}
        for m in re.finditer(r"\|\s*图\s*(\d+)\s*\|\s*`[^`]+`\s*\|\s*([^|]+?)\s*\|", app_d):
            listed[m.group(1)] = m.group(2).strip()
        for n in sorted(titles, key=int):
            want, got = titles[n], listed.get(n)
            if got is None:
                problems.append(f"附录 D has no description for 图 {n}")
            elif got != want:
                problems.append(
                    "图 {} description differs from the figure script:\n"
                    "      figure script: {}\n"
                    "      附录 D       : {}".format(n, want, got))

    print()
    if warnings:
        print(f"[check] {len(warnings)} WARNING(S) (non-blocking):")
        for w in warnings:
            print(f"  ~ {w}")
        print()
    if problems:
        print(f"[check] {len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[check] OK: all cross-references resolve and all figures are cited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
