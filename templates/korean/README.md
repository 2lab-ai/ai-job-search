# Korean (Hangul) rendering support

`korean-fonts.sty` is a shared preamble for the **stock** templates - not a registered template.
It is not managed by `/add-template` and does not follow the `templates/cv/<name>/` layout in
[../README.md](../README.md): there is no alternative CV design here, only the font setup that the
stock moderncv CV and `cover.cls` cover letter are missing for Korean.

Opt in with one line, and point `TEXINPUTS` at this folder so the engine finds the file:

```bash
# CV - same engine as the English CV
cd cv && TEXINPUTS=../templates/korean: lualatex -interaction=nonstopmode main_<company>_<role>.tex

# Cover letter - same engine as the English letter
cd cover_letters && TEXINPUTS=../templates/korean: xelatex -interaction=nonstopmode cover_<company>_<role>.tex
```

```latex
\usepackage{korean-fonts}
```

Nothing is installed into your TeX tree and nothing changes for English documents: a document that
does not load the package compiles exactly as before.

Requirements, both of which the package checks and reports by name rather than rendering blank
boxes: a Unicode engine (lualatex or xelatex, never pdflatex) and ko.TeX with a Korean font
(`sudo apt install texlive-lang-korean`, or `tlmgr install collection-langkorean`).

Full usage, the translated-heading list and the Korean verification steps live in
`.claude/skills/job-application-assistant/05-cv-templates.md` and `06-cover-letter-templates.md`.
The compiled references are `tests/fixtures/korean-cv.tex` (2 pages, lualatex) and
`tests/fixtures/korean-cover.tex` (1 page, xelatex), which CI compiles on every push.
