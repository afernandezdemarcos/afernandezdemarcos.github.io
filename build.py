#!/usr/bin/env python3
"""Build the website from LaTeX sources (requires Python 3.9+ and pandoc 3).

  content/<path>.tex        ->  public/<path>/index.html
  content/<dir>/index.tex   ->  public/<dir>/index.html
  content/404.tex           ->  public/404.html
  content/** (other files)  ->  copied as-is (images, bib files, ...)
  static/**                 ->  copied as-is to the site root

Files and folders whose name starts with "_" are not published (use them for
pieces you \\input from other pages).

Usage:
  python3 build.py            build into public/
  python3 build.py --serve    build, serve at http://localhost:8000 and rebuild on changes
"""

import argparse
import functools
import html
import http.server
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
STATIC = ROOT / "static"
LAYOUT = ROOT / "layout"
SITE_CONFIG = ROOT / "site.tex"
MACROS = ROOT / "macros.tex"

SPLIT = "@@@SPLIT@@@"


# ---------------------------------------------------------------------------
# Small LaTeX helpers
# ---------------------------------------------------------------------------

def strip_comments(tex):
    """Remove LaTeX comments (an unescaped % up to the end of the line)."""
    return re.sub(r"(?<!\\)%.*", "", tex)


def read_group(tex, pos):
    """Read a {...} group starting at tex[pos] (after optional whitespace).

    Returns (content, position after the closing brace), or (None, pos).
    """
    i = pos
    while i < len(tex) and tex[i] in " \t\n":
        i += 1
    if i >= len(tex) or tex[i] != "{":
        return None, pos
    depth, start = 0, i
    while i < len(tex):
        if tex[i] == "\\":
            i += 2
            continue
        if tex[i] == "{":
            depth += 1
        elif tex[i] == "}":
            depth -= 1
            if depth == 0:
                return tex[start + 1:i], i + 1
        i += 1
    raise ValueError("unbalanced braces near: " + tex[start:start + 60])


def find_commands(tex, name, nargs):
    """Yield (start, end, args) for every \\name{..}...{..} in tex."""
    for m in re.finditer(r"\\" + name + r"(?![A-Za-z])", tex):
        args, pos = [], m.end()
        for _ in range(nargs):
            arg, pos = read_group(tex, pos)
            if arg is None:
                break
            args.append(arg)
        else:
            yield m.start(), pos, args


# ---------------------------------------------------------------------------
# Site configuration (site.tex)
# ---------------------------------------------------------------------------

def load_config():
    tex = strip_comments(SITE_CONFIG.read_text(encoding="utf-8"))

    def one(name, default=""):
        found = [a[0].strip() for _, _, a in find_commands(tex, name, 1)]
        return found[-1] if found else default

    return {
        "title": one("sitetitle"),
        "url": one("siteurl").rstrip("/"),
        "description": one("sitedescription"),
        "author": one("siteauthor"),
        "lang": one("sitelang", "en"),
        "favicon": one("favicon"),
        "footer": [a for _, _, a in find_commands(tex, "footer", 2)][-1:],
        "menu": [a for _, _, a in find_commands(tex, "menuitem", 2)],
        "social": [a for _, _, a in find_commands(tex, "social", 3)],
        "redirects": [a for _, _, a in find_commands(tex, "redirect", 2)],
    }


# ---------------------------------------------------------------------------
# Web-only commands, replaced by raw HTML before pandoc runs
# ---------------------------------------------------------------------------

class RawHTML:
    """Stores HTML snippets and hands out tokens that survive pandoc."""

    def __init__(self):
        self.snippets = []

    def block(self, snippet):
        self.snippets.append(snippet)
        return f"\n\nRAWHTML{len(self.snippets) - 1}X\n\n"

    def inline(self, snippet):
        self.snippets.append(snippet)
        return f"RAWHTML{len(self.snippets) - 1}X"

    def restore(self, body):
        for i, snippet in enumerate(self.snippets):
            token = f"RAWHTML{i}X"
            body = body.replace(f"<p>{token}</p>", snippet).replace(token, snippet)
        return body


def web_commands(raw):
    """name -> (number of arguments, function returning the replacement)."""
    esc = functools.partial(html.escape, quote=True)
    return {
        # \avatar{/avatar.jpg}: round picture floating on the right
        "avatar": (1, lambda src: raw.block(
            f'<figure class="avatar"><img src="{esc(src)}" alt="avatar"></figure>')),
        # \icon{fas fa-file}: a Font Awesome icon
        "icon": (1, lambda cls: raw.inline(f'<i class="{esc(cls)}"></i>')),
        # \done: a ticked checkbox (e.g. books already read)
        "done": (0, lambda: raw.inline('<input type="checkbox" checked disabled> ')),
        # \maketitle and \tableofcontents behave as in LaTeX
        "maketitle": (0, lambda: raw.block("@@MAKETITLE@@")),
        "tableofcontents": (0, lambda: raw.block("@@TOC@@")),
    }


def preprocess(tex, raw):
    # \begin{html} ... \end{html}: raw HTML, copied verbatim
    tex = re.sub(r"\\begin\{html\}(.*?)\\end\{html\}",
                 lambda m: raw.block(m.group(1).strip()), tex, flags=re.S)
    for name, (nargs, make) in web_commands(raw).items():
        # Replace from the end so that earlier positions stay valid.
        for start, end, args in reversed(list(find_commands(tex, name, nargs))):
            tex = tex[:start] + make(*args) + tex[end:]
    return tex


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def output_path(src, out):
    rel = src.relative_to(CONTENT).with_suffix("")
    if rel.name == "404":
        return out / "404.html"
    if rel.name == "index":
        return out / rel.parent / "index.html"
    return out / rel / "index.html"


def url_of(page, out):
    rel = page.relative_to(out).as_posix()
    return "/" + rel[: -len("index.html")] if rel.endswith("index.html") else "/" + rel


def convert(src, dest, out):
    """Run pandoc on one .tex file. Returns a dict with body and metadata."""
    raw = RawHTML()
    tex = src.read_text(encoding="utf-8")
    code = strip_comments(tex)
    is_document = re.search(r"\\documentclass", code) is not None
    tex = preprocess(tex, raw)

    # Relative links/images are written relative to the .tex file; the page
    # lives one folder deeper (foo.tex -> foo/index.html) unless it is an index.
    depth = len(dest.parent.relative_to(out).parts) - len(
        src.parent.relative_to(CONTENT).parts)
    cmd = [
        "pandoc", "--from=latex", "--to=html5", "--wrap=none",
        "--standalone", f"--template={LAYOUT / 'fragment.pandoc'}",
        "--math-method=mathjax", "--shift-heading-level-by=1",
        f"--lua-filter={LAYOUT / 'filter.lua'}",
        "--toc",  # only printed where \tableofcontents appears
    ]
    if depth > 0:
        cmd.append(f"--metadata=rel_prefix:{'../' * depth}")
    if is_document:
        cmd.append("--number-sections")
    if re.search(r"\\(bibliography|addbibresource)\s*\{", code):
        cmd.append("--citeproc")

    # Standalone documents (notes) bring their own preamble; simple pages get
    # the shared macros.
    prelude = "" if is_document else MACROS.read_text(encoding="utf-8") + "\n"
    result = subprocess.run(cmd, input=prelude + tex, capture_output=True, text=True,
                            encoding="utf-8", cwd=src.parent)
    # Report line numbers of the .tex file, not of macros + .tex
    offset = prelude.count("\n")
    stderr = re.sub(r"line (\d+)", lambda m: f"line {max(int(m.group(1)) - offset, 1)}",
                    result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed on {src.relative_to(ROOT)}:\n{stderr}")
    for line in stderr.splitlines():
        print(f"  [{src.relative_to(ROOT)}] {line}", file=sys.stderr)

    body, toc, pagetitle, title, authors, date, abstract = result.stdout.split(SPLIT)
    title_block = ""
    if title.strip():
        title_block = f'<header class="title-block">\n<h1 class="title">{title.strip()}</h1>\n'
        if authors.strip():
            title_block += f'<p class="author">{authors.strip()}</p>\n'
        if date.strip():
            title_block += f'<p class="date">{date.strip()}</p>\n'
        if abstract.strip():
            title_block += f'<div class="abstract">\n<p class="abstract-title">Abstract</p>\n{abstract.strip()}\n</div>\n'
        title_block += "</header>"
    toc_block = f'<nav class="toc">\n<p class="toc-title">Contents</p>\n{toc.strip()}\n</nav>'

    body = raw.restore(body.strip())
    body = body.replace("<p>@@MAKETITLE@@</p>", title_block).replace("@@MAKETITLE@@", title_block)
    body = body.replace("<p>@@TOC@@</p>", toc_block).replace("@@TOC@@", toc_block)
    return {
        "body": body,
        "title": html.unescape(pagetitle.strip()),
        "is_document": is_document,
    }


def render(template, page, config):
    menu = '\n<span class="nav-sep">/</span>\n'.join(
        f'<a class="nav-link" href="{html.escape(url)}">{html.escape(name)}</a>'
        for name, url in config["menu"])
    social = "\n".join(
        f'<a href="{html.escape(url)}" class="{html.escape(icon)}" title="{html.escape(title)}"'
        f' aria-label="{html.escape(title)}"></a>'
        for icon, title, url in config["social"])
    footer = ""
    for text, url in config["footer"]:
        footer = f'<a href="{html.escape(url)}"><small>{html.escape(text)}</small></a>'
    math = ""
    if 'class="math' in page["body"]:
        math = (LAYOUT / "mathjax.html").read_text(encoding="utf-8")
    favicon = ""
    if config["favicon"]:
        favicon = f'<link rel="icon" href="{html.escape(config["favicon"])}">'

    title = page["title"] or config["title"]
    values = {
        "lang": config["lang"],
        "title": html.escape(title),
        "description": html.escape(config["description"]),
        "author": html.escape(config["author"]),
        "favicon": favicon,
        "math": math,
        "site_title": html.escape(config["title"]),
        "menu": menu,
        "body_class": "document" if page["is_document"] else "page",
        "content": page["body"],
        "social": social,
        "footer": footer,
    }
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], template)


def publishable(path, base):
    return not any(part.startswith(("_", ".")) for part in path.relative_to(base).parts)


def build(out):
    start = time.time()
    config = load_config()
    template = (LAYOUT / "page.html").read_text(encoding="utf-8")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if STATIC.exists():
        shutil.copytree(STATIC, out, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".*"))
    shutil.copy(LAYOUT / "style.css", out / "style.css")

    pages, errors = [], 0
    for src in sorted(CONTENT.rglob("*")):
        if not src.is_file() or not publishable(src, CONTENT):
            continue
        if src.suffix != ".tex":
            dest = out / src.relative_to(CONTENT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest)
            continue
        dest = output_path(src, out)
        try:
            page = convert(src, dest, out)
        except ValueError as e:
            print(f"error in {src.relative_to(ROOT)}: {e}", file=sys.stderr)
            errors += 1
            continue
        except RuntimeError as e:
            print(e, file=sys.stderr)
            errors += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(template, page, config), encoding="utf-8")
        if dest.name != "404.html":
            pages.append(url_of(dest, out))

    for source, target in config["redirects"]:
        dest = out / source.strip("/") / "index.html"
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        t = html.escape(target)
        dest.write_text(
            f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>Redirecting…</title>'
            f'<link rel="canonical" href="{t}"><meta http-equiv="refresh" content="0; url={t}">'
            f'</head><body><a href="{t}">{t}</a></body></html>\n', encoding="utf-8")

    sitemap = "\n".join(f"  <url><loc>{html.escape(config['url'] + p)}</loc></url>" for p in pages)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{sitemap}\n</urlset>\n", encoding="utf-8")
    (out / ".nojekyll").touch()

    print(f"Built {len(pages)} pages into {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}"
          f" in {time.time() - start:.1f}s" + (f" with {errors} error(s)" if errors else ""))
    return errors


# ---------------------------------------------------------------------------
# Local preview
# ---------------------------------------------------------------------------

def snapshot():
    watched = [CONTENT, STATIC, LAYOUT, SITE_CONFIG, MACROS]
    files = []
    for w in watched:
        files.extend(w.rglob("*") if w.is_dir() else [w])
    return {f: f.stat().st_mtime for f in files if f.is_file()}


def serve(out, port):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    httpd = http.server.ThreadingHTTPServer(("localhost", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Serving at http://localhost:{port}/  (Ctrl+C to stop; reload the browser after edits)")
    state = snapshot()
    try:
        while True:
            time.sleep(1)
            new = snapshot()
            if new != state:
                state = new
                try:
                    build(out)
                except Exception as e:  # keep serving while the error is fixed
                    print(f"build failed: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        httpd.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "public"), help="output folder")
    parser.add_argument("--serve", action="store_true", help="serve locally and rebuild on changes")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not installed (macOS: brew install pandoc)")
    out = Path(args.out).resolve()
    errors = build(out)
    if args.serve:
        serve(out, args.port)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
