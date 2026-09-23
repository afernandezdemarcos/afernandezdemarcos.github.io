# afernandezdemarcos.github.io

Personal website, written in LaTeX and converted to HTML with
[pandoc](https://pandoc.org) by a small script (`build.py`). No Hugo and no theme.
GitHub Actions deploys every push to `main`.

## Layout

```
site.tex            site title, menu, footer icons, redirects
macros.tex          \newcommand's available in every page (\doi, \pdflink, \R, ...)
content/            one .tex file per page (URL = path)
static/             files copied as-is (PDFs, images): static/x.pdf -> /x.pdf
templates/note.tex  starting point for a new note
layout/             HTML template, CSS, pandoc filter (only for changing the design)
build.py            the build script
```

URLs follow the file names:

| File                         | URL                   |
|------------------------------|-----------------------|
| `content/index.tex`          | `/`                   |
| `content/research.tex`       | `/research/`          |
| `content/teaching/main.tex`  | `/teaching/main/`     |
| `content/notes/index.tex`    | `/notes/`             |
| `content/404.tex`            | page for broken links |

Files or folders starting with `_` are not published. Use them for pieces
you `\input` from another page.

## Local preview

You need Python 3 and pandoc (`brew install pandoc`).

```sh
python3 build.py --serve     # http://localhost:8000, rebuilds when you save
python3 build.py             # just build into public/
```

## Writing pages

A page is a LaTeX fragment with a `\title`. There is no preamble and no
`\begin{document}`:

```latex
\title{Research}

\section*{Publications}
\begin{enumerate}
  \item Author (2026). Title. \emph{Journal}~\textbf{1}, 1--2. \doi{10.1000/xyz} \pdflink{/paper.pdf}
\end{enumerate}
```

- `\section` → big heading, `\subsection` → medium, `\subsubsection` → small.
  On pages, use the starred versions (`\section*`) to avoid numbering.
- `enumerate` renders as `[1] [2] ...`, `itemize` as bullets, and `tabular`
  with `\hline` after the first row as a table with a header.
- Math works as usual: `$...$`, `\[...\]`, `equation`, `align`.
- Links: `\href{url}{text}`. External links and PDFs open in a new tab.
- `\textbf`, `\emph`, `\textcolor{red}{...}`, `\\` (line break), `~`, `--` all work.
- `\maketitle` prints the `\title` as a big heading. Without it, the title
  is only used in the browser tab.

Web-only commands, in addition to what's in `macros.tex`:

| Command                          | Result                                  |
|----------------------------------|-----------------------------------------|
| `\avatar{/avatar.jpg}`           | round picture on the right              |
| `\icon{fas fa-file-lines}`       | [Font Awesome](https://fontawesome.com/search?ic=free) icon |
| `\done`                          | ticked checkbox                         |
| `\begin{html} ... \end{html}`    | raw HTML (maps, videos, ...)            |

## Notes (full LaTeX documents)

Copy `templates/note.tex` to e.g. `content/notes/uniformity.tex`; it is
published at `/notes/uniformity/`. Any file with `\documentclass` is treated
as a note:

- It keeps its own preamble. Your `\newcommand`s and `\newtheorem`s are used,
  and `macros.tex` is *not* added.
- Sections are numbered, `\maketitle`, `abstract` and `\tableofcontents` work,
  and so do theorem environments, `proof`, `\label`/`\ref`/`\eqref`, footnotes
  and figures.
- Citations: put the `.bib` next to the `.tex` and use
  `\bibliography{refs}` (or `\addbibresource{refs.bib}`) with `\cite`.
- Images: put `.png`/`.jpg`/`.svg` files next to the `.tex` and
  `\includegraphics` them. TikZ and PDF images are not converted; export
  them to SVG/PNG.
- The same file still compiles with `pdflatex`. To offer the PDF too, put it
  in `static/` and link it with `\href`.

Link the note from any page (e.g. `\href{/notes/uniformity/}{Uniformity}`),
or add it to the menu.

## Menu and footer

Everything is in `site.tex`. Entries appear in the order written, and there
is no limit on how many. If they don't fit next to the name, they move to
a second line.

```latex
\menuitem{Research}{/research/}
\menuitem{Notes}{/notes/}
```

## Deployment

`.github/workflows/deploy.yml` installs pandoc, runs `python3 build.py` and
publishes `public/` to GitHub Pages on every push to `main`. Pushes to other
branches only build, as a check. In the repository settings, *Pages →
Source* must be **GitHub Actions**.
