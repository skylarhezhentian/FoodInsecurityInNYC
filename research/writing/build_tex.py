#!/usr/bin/env python3
"""Regenerate research_paper.tex from research_paper.md.

Reproduces the hand-tuned pandoc style used for this paper:
  - title / author / date / multi-paragraph abstract via metadata
  - colored hyperlinks (NavyBlue / Maroon / Blue)
  - fixed-width figures (0.92\\linewidth) instead of \\pandocbounded
  - no markdown horizontal rules, no redundant "*Figure N. ...*" lines
  - pdflatex-safe table glyphs: checkmark -> $\\checkmark$, circle -> $\\circ$

Usage:  python3 build_tex.py      (run from the project directory)
Requires pandoc on PATH. Replaces the lost /tmp/mk_tex.py from earlier sessions.
"""
import re, subprocess, pathlib, tempfile, os

ROOT = pathlib.Path(__file__).resolve().parent
md = (ROOT / "research_paper.md").read_text()

# Title is taken from the leading H1 of the markdown.
TITLE = re.search(r"(?m)^# (.+)$", md).group(1).strip()

# Abstract: text between '## Abstract' and the following horizontal rule.
abstract = re.search(r"## Abstract\s*\n+(.*?)\n+---\n", md, re.S).group(1).strip()

# Body starts at the first numbered section.
body = md[md.index("## 1. Introduction"):]
body = re.sub(r"(?m)^---\s*$", "", body)                      # drop hrules
body = re.sub(r"(?m)^\*Figure \d+\..*\*\s*$", "", body)        # drop italic figure lines
body = re.sub(r"(!\[)Figure \d+\.\s*", r"\1", body)            # drop "Figure N." from alt text

abs_yaml = "\n".join("  " + ln if ln.strip() else "" for ln in abstract.split("\n"))
meta = f"""---
title: |
  {TITLE}
author: Laidlaw Undergraduate Research Program
date: June 2026
abstract: |
{abs_yaml}
fontsize: 11pt
geometry: margin=1in
colorlinks: true
linkcolor: NavyBlue
filecolor: Maroon
citecolor: Blue
urlcolor: NavyBlue
---

"""

with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
    f.write(meta + body)
    tmp = f.name

out = ROOT / "research_paper.tex"
subprocess.run(
    ["pandoc", tmp, "--standalone", "--shift-heading-level-by=-1", "-o", str(out)],
    check=True,
)
os.unlink(tmp)

tex = out.read_text()
tex = tex.replace(
    r"\pandocbounded{\includegraphics[keepaspectratio,",
    r"\includegraphics[width=0.92\linewidth,height=\textheight,keepaspectratio,",
)
tex = re.sub(r"(\]\{[^}]+\.png\})\}", r"\1", tex)
tex = tex.replace("✓", r"$\checkmark$").replace("○", r"$\circ$")
out.write_text(tex)
print("wrote", out)
