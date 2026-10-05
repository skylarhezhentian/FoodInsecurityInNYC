# Original poster source archive

These files were copied byte for byte from `Skylar_Tian_Laidlaw_Poster.zip`.
The archive is a strong source match for the [supplied poster](../Skylar_Tian_Laidlaw_Poster.pdf):
its title, wording, tables, and figure references agree, and both figure images
and the Columbia logo have exactly the same RGB and transparency pixels as the
images embedded in the PDF. [The manifest](manifest.json) records the archive
hash, every copied file hash, and those image comparisons.

No source build was executed. This does not establish a byte-identical PDF build,
and the historical text and claims have not been updated to the corrected model.
See [the poster guide](../README.md) for that distinction and
[the reference guide](../references.md) for bibliographic corrections.

## Files and build dependencies

- `poster.tex` is the entry point, a 120 × 90 cm Beamer poster.
- `figures/fig_equity_layer_poster.png` is Figure 1; `figures/fig_dial_poster.png`
  is Figure 2. The source also uses the white Columbia logo. The Laidlaw logo is
  drawn with inline TikZ paths; its SVG is retained as an original asset.
- `beamerthemegemini.sty` and `beamercolorthemecam.sty` are the selected themes.
  The other theme files are original template alternatives.
- The supplied `Makefile` invokes `latexmk` with LuaLaTeX and no shell-escape
  option. `.latexmkrc` controls bibliography and cleanup behavior. Neither file
  downloads anything or invokes the routing solver.
- LaTeX dependencies include Beamer/beamerposter, fontspec, unicode-math, TikZ,
  pgfplots, biblatex/Biber, and the packages named in `poster.tex` and the theme.
  Fonts include Raleway and Lato, loaded by the theme before the poster overrides
  its typography with TeX Gyre Termes and TeX Gyre Termes Math.
- References are manually typeset in `poster.tex`. `ref.bib` is declared but no
  bibliography is printed from it. `poster.bib` contains an unused Shannon entry
  left over from the template.

The original [template README](TEMPLATE_README.md) describes Gemini. It was
relocated without changing its contents so this folder opens with project-specific
source guidance. The template’s
[MIT license](LICENSE.md) and copyright notice are preserved; this license is
for the template and is not a blanket license for institutional logos or other
third-party material.
