# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pymupdf>=1.24",
# ]
# ///
"""
Fetch a paper's metadata, figures, and tables for filling in a project-page
`template.yaml`. Works from an arXiv link/id OR a direct PDF (URL or local file).

Run it through uv so the PEP 723 header above provides the (only) dependency,
PyMuPDF, which is used solely for the PDF path — the arXiv path is pure stdlib:

    pixi run uv run scripts/fetch_arxiv.py <arxiv-url-or-id> --out /tmp/paper.json
    pixi run uv run scripts/fetch_arxiv.py --pdf paper.pdf   --out /tmp/paper.json

Two-phase, so the skill keeps control of *which* images matter:

  1. List mode (default): emit a JSON summary of every figure/table (arXiv) or
     every embedded image + the first pages of text (PDF). Downloads/saves
     nothing. Each selectable image has a stable `id`.

  2. Save mode: pass --teaser <id> and/or --method <id[,id,...]> (ids as shown
     in list mode; a bare integer N is accepted as the arXiv "Figure N") to
     write just those images into --public-dir as teaser.<ext> / method.<ext> /
     method2.<ext>… The `saved` block echoes the real filenames back.

arXiv input accepts: https://arxiv.org/abs/2312.02008v1 · /html/… · /pdf/… ·
2312.02008v1 · 2312.02008. PDF input: any local path or http(s) URL to a .pdf.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

UA = "Mozilla/5.0 (projectpage-template arxiv-to-projectpage skill)"


def eprint(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def parse_arxiv_id(s):
    s = s.strip()
    m = re.search(r'(\d{4}\.\d{4,5})(v\d+)?', s)
    if not m:
        m = re.search(r'([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?', s)
    if not m:
        raise SystemExit(f"Could not find an arXiv id in: {s!r}")
    return m.group(1) + (m.group(2) or "")


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def strip_tags(s):
    s = re.sub(r'<[^>]+>', ' ', s)
    return html.unescape(re.sub(r'\s+', ' ', s)).strip()


def safe_ext(src, allowed, default=".png"):
    ext = os.path.splitext(src.split("?")[0])[1].lower()
    return ext if ext in allowed else default


def parse_id_list(s):
    return [x for x in re.split(r'[,\s]+', s.strip()) if x] if s else []


def build_bibtex(arxiv_id, meta):
    bare = re.sub(r'v\d+$', '', arxiv_id) if arxiv_id else ""
    last = "unknown"
    if meta.get("authors"):
        last = re.sub(r'[^A-Za-z]', '', meta["authors"][0].split()[-1]).lower() or "unknown"
    key = f"{last}{meta.get('year','')}arxiv"
    authors = " and ".join(meta.get("authors", []))
    journal = f"arXiv preprint arXiv:{bare}" if bare else "preprint"
    return (f"@article{{{key},\n"
            f"  title={{{meta.get('title','')}}},\n"
            f"  author={{{authors}}},\n"
            f"  journal={{{journal}}},\n"
            f"  year={{{meta.get('year','')}}}\n"
            f"}}")


# ---------------------------------------------------------------------------
# arXiv metadata (Atom API)
# ---------------------------------------------------------------------------
def get_metadata(arxiv_id):
    bare = re.sub(r'v\d+$', '', arxiv_id)
    xml = fetch(f"http://export.arxiv.org/api/query?id_list={bare}&max_results=1")
    entry = re.search(r'<entry>(.*?)</entry>', xml, re.S)
    entry = entry.group(1) if entry else xml

    def tag(name, s=entry):
        m = re.search(rf'<{name}>(.*?)</{name}>', s, re.S)
        return html.unescape(re.sub(r'\s+', ' ', m.group(1)).strip()) if m else ""

    published = tag("published")
    authors = [html.unescape(re.sub(r'\s+', ' ', a).strip())
               for a in re.findall(r'<author>\s*<name>(.*?)</name>', entry, re.S)]
    cats = re.findall(r'<category[^>]*term="([^"]+)"', entry)
    return {"title": tag("title"), "abstract": tag("summary"), "authors": authors,
            "year": published[:4] if published else "",
            "primary_category": cats[0] if cats else "", "doi": tag("arxiv:doi")}


# ---------------------------------------------------------------------------
# arXiv HTML: figures, standalone graphics, tables
# ---------------------------------------------------------------------------
class FigureTableParser(HTMLParser):
    """Collect top-level <figure class="ltx_figure|ltx_table"> blocks (raw inner
    HTML), and standalone <img class="ltx_graphics"> that live OUTSIDE any figure
    (the uncaptioned pull figures many papers put at the very top)."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.figures, self.tables, self.graphics = [], [], []
        self._stack, self._depth = [], 0
        self._fig_depth = None  # depth at which we're inside a figure

    def handle_starttag(self, tag, attrs):
        self._depth += 1
        a = dict(attrs)
        if tag == "figure":
            cls = a.get("class", "")
            kind = "table" if "ltx_table" in cls else ("figure" if "ltx_figure" in cls else None)
            if kind and not self._stack:
                self._stack.append([kind, self._depth, []])
                self._fig_depth = self._depth
        elif tag == "img" and not self._stack:
            cls = a.get("class", "")
            src = a.get("src", "")
            if "ltx_graphics" in cls and src and not src.startswith("data:"):
                self.graphics.append({"src": html.unescape(src),
                                      "width": a.get("width"), "height": a.get("height")})
        if self._stack:
            self._stack[-1][2].append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self._depth -= 1  # self-closing: undo the increment

    def handle_endtag(self, tag):
        if self._stack:
            self._stack[-1][2].append(f"</{tag}>")
            if tag == "figure" and self._depth == self._stack[-1][1]:
                kind, _, buf = self._stack.pop()
                raw = "".join(buf)
                (self.tables if kind == "table" else self.figures).append(raw)
                self._fig_depth = None
        self._depth -= 1

    def handle_data(self, data):
        if self._stack:
            self._stack[-1][2].append(data)

    def handle_entityref(self, name):
        if self._stack:
            self._stack[-1][2].append(f"&{name};")

    def handle_charref(self, name):
        if self._stack:
            self._stack[-1][2].append(f"&#{name};")


def caption_number(caption, kind):
    m = re.match(rf'\s*{kind}\s+(\d+)', caption, re.I)
    return int(m.group(1)) if m else None


def extract_caption(raw):
    m = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', raw, re.S)
    return strip_tags(m.group(1)) if m else ""


def first_img_src(raw):
    m = re.search(r'<img[^>]*\ssrc="([^"]+)"', raw)
    return html.unescape(m.group(1)) if m else None


def extract_svg(raw):
    m = re.search(r'<svg\b.*?</svg>', raw, re.S)
    return m.group(0) if m else None


def catalog_html_images(fp):
    """Unify figures + standalone graphics into one list of selectable images.
    `id`: F<order> for figures, G<order> for standalone graphics. `figure`: the
    real Figure number (or null). `image_kind`: raster | svg | none."""
    images = []
    for order, raw in enumerate(fp.figures, 1):
        caption = extract_caption(raw)
        src = first_img_src(raw)
        if src and not src.startswith("data:"):
            kind, keep_src, svg = "raster", src, None
        elif extract_svg(raw):
            kind, keep_src, svg = "svg", None, extract_svg(raw)
        else:
            kind, keep_src, svg = "none", None, None
        images.append({"id": f"F{order}", "figure": caption_number(caption, "Figure"),
                       "caption": caption, "image_kind": kind, "has_image": kind != "none",
                       "src": keep_src, "_svg": svg})
    for gi, g in enumerate(fp.graphics, 1):
        images.append({"id": f"G{gi}", "figure": None,
                       "caption": "(uncaptioned graphic near top of paper)",
                       "image_kind": "raster", "has_image": True, "src": g["src"],
                       "_svg": None, "width": g.get("width"), "height": g.get("height")})
    return images


# ---- Table -> uk-table HTML ------------------------------------------------
class TabularParser(HTMLParser):
    """Grid of cells from <table class="ltx_tabular">, tracking header rows,
    bold, colspan, rowspan. Math is taken from the TeX <annotation> (so we don't
    duplicate MathML presentation text) with ^{}/_{} mapped to <sup>/<sub>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.header_rows = [], set()
        self._row = self._cell = None
        self._in_thead = False
        self._row_is_header = False
        self._math = 0          # depth inside <math>
        self._ann = 0           # depth inside TeX <annotation>
        self._math_tex = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._row, self._row_is_header = [], self._in_thead
        elif tag in ("td", "th"):
            # A cell is bold if the cell itself carries the bold class; inline
            # <b>/<strong>/bold-span below can also flip it on. Per-cell, so bold
            # never leaks across cells (an unmatched </td> can't unbalance a counter).
            self._cell = {"text": "", "bold": "ltx_font_bold" in cls,
                          "is_th": tag == "th" or "ltx_th" in cls,
                          "colspan": int(a.get("colspan", 1) or 1), "rowspan": int(a.get("rowspan", 1) or 1)}
        elif tag == "math":
            self._math += 1
            self._math_tex = ""
        elif tag == "annotation" and a.get("encoding") == "application/x-tex":
            self._ann += 1
        elif (tag in ("b", "strong") or "ltx_font_bold" in cls) and self._cell is not None:
            self._cell["bold"] = True
        elif tag == "br" and self._cell is not None:
            self._cell["text"] += " / "

    def handle_endtag(self, tag):
        if tag == "thead":
            self._in_thead = False
        elif tag == "tr":
            if self._row and any(c["text"].strip() for c in self._row):
                if self._row_is_header or all(c["is_th"] for c in self._row):
                    self.header_rows.add(len(self.rows))
                self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._cell["text"] = re.sub(r'\s+', ' ', self._cell["text"]).strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "math":
            self._math = max(0, self._math - 1)
            if self._math == 0 and self._cell is not None:
                self._cell["text"] += tex_to_html(self._math_tex)
        elif tag == "annotation":
            self._ann = max(0, self._ann - 1)

    def handle_data(self, data):
        if self._cell is None:
            return
        if self._math:
            if self._ann:
                self._math_tex += data
            return
        self._cell["text"] += data


def tex_to_html(tex):
    tex = (tex or "").strip()
    tex = re.sub(r'\^\{([^{}]*)\}', r'<sup>\1</sup>', tex)
    tex = re.sub(r'_\{([^{}]*)\}', r'<sub>\1</sub>', tex)
    tex = re.sub(r'\^(\w)', r'<sup>\1</sup>', tex)
    tex = re.sub(r'_(\w)', r'<sub>\1</sub>', tex)
    tex = tex.replace(r'\%', '%').replace(r'\times', '×').replace(r'\pm', '±')
    tex = re.sub(r'\\(?:mathrm|mathbf|text|mathit)\{([^{}]*)\}', r'\1', tex)
    return tex


def table_to_ukhtml(raw):
    caption = extract_caption(raw)
    m = re.search(r'<table[^>]*class="[^"]*ltx_tabular[^"]*".*?</table>', raw, re.S)
    if not m:
        return None
    p = TabularParser()
    p.feed(m.group(0))
    if not p.rows:
        return None

    def cell(c, tag):
        t = c["text"]  # already contains inline <sup>/<sub> from math
        # escape only the non-tag text: our own tags are <b>/<sup>/<sub>
        t = re.sub(r'&(?!(?:amp|lt|gt|#\d+|sup|/sup|sub|/sub|b|/b);)', '&amp;', t)
        if c["bold"]:
            t = f"<b>{t}</b>"
        span = (f' colspan="{c["colspan"]}"' if c["colspan"] > 1 else "") + \
               (f' rowspan="{c["rowspan"]}"' if c["rowspan"] > 1 else "")
        return f"<{tag}{span}>{t}</{tag}>"

    # Header rows: the contiguous leading rows that are either flagged headers
    # (inside <thead> / all-<th>) or entirely bold — this pulls a bold "N object
    # level | (%) (%)" sub-header row up into <thead> instead of stranding it in
    # the body. Data rows that merely bold their winning value aren't all-bold,
    # so they stay in <tbody>.
    header_idx, i = [], 0
    while i < len(p.rows) and (i in p.header_rows or all(c["bold"] for c in p.rows[i])):
        header_idx.append(i)
        i += 1
    if not header_idx:
        header_idx = [0]
    header_set = set(header_idx)
    L = ['<div class="uk-overflow-auto">',
         '  <table class="uk-table uk-table-small uk-text-small uk-table-divider">',
         '    <thead>']
    for i in header_idx:
        L.append("      <tr>" + "".join(cell(c, "th") for c in p.rows[i]) + "</tr>")
    L.append("    </thead>")
    L.append("    <tbody>")
    for i, row in enumerate(p.rows):
        if i in header_set:
            continue
        L.append("      <tr>" + "".join(cell(c, "td") for c in row) + "</tr>")
    L += ["    </tbody>", "  </table>", "</div>"]
    return {"number": caption_number(caption, "Table"), "caption": caption, "html": "\n".join(L)}


# ---------------------------------------------------------------------------
# Saving images (arXiv figures/graphics or PDF images)
# ---------------------------------------------------------------------------
def save_html_image(img, base_url, public_dir, stem):
    if img["image_kind"] == "svg":
        dest = os.path.join(public_dir, stem + ".svg")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(img["_svg"])
        eprint(f"  saved {img['id']} (svg) -> {dest} ({len(img['_svg'])} B)")
        return {"id": img["id"], "figure": img["figure"], "saved_as": os.path.basename(dest),
                "path": dest, "bytes": len(img["_svg"]), "kind": "svg", "src": "inline-svg"}
    ext = safe_ext(img["src"], (".png", ".jpg", ".jpeg", ".gif", ".webp"))
    dest = os.path.join(public_dir, stem + ext)
    data = fetch(urljoin(base_url, img["src"]), binary=True)
    with open(dest, "wb") as f:
        f.write(data)
    eprint(f"  saved {img['id']} -> {dest} ({len(data)} B)")
    return {"id": img["id"], "figure": img["figure"], "saved_as": os.path.basename(dest),
            "path": dest, "bytes": len(data), "kind": "raster", "src": urljoin(base_url, img["src"])}


def resolve_id(images, token):
    """Accept an explicit id (F3/G1/P2), or a bare int N == arXiv Figure N."""
    token = token.strip()
    by_id = {im["id"]: im for im in images}
    if token in by_id:
        return by_id[token]
    if re.fullmatch(r'\d+', token):
        n = int(token)
        for im in images:
            if im.get("figure") == n and im["has_image"]:
                return im
        # fall back to positional F<n>
        return by_id.get(f"F{n}")
    return None


def do_saves(images, base_url, public_dir, teaser, method, figures, saver):
    saved = {"teaser": None, "method": [], "figures": []}
    if teaser:
        im = resolve_id(images, teaser)
        if im and im["has_image"]:
            saved["teaser"] = saver(im, base_url, public_dir, "teaser")
        else:
            eprint(f"WARN: teaser id {teaser!r} not found / no image")
    for i, tok in enumerate(parse_id_list(method)):
        im = resolve_id(images, tok)
        if im and im["has_image"]:
            saved["method"].append(saver(im, base_url, public_dir, "method" if i == 0 else f"method{i+1}"))
        else:
            eprint(f"WARN: method id {tok!r} not found / no image")
    for tok in parse_id_list(figures):
        im = resolve_id(images, tok)
        if im and im["has_image"]:
            saved["figures"].append(saver(im, base_url, public_dir, f"fig_{im['id']}"))
        else:
            eprint(f"WARN: figure id {tok!r} not found / no image")
    return saved


# ---------------------------------------------------------------------------
# PDF path (PyMuPDF)
# ---------------------------------------------------------------------------
def load_pdf_bytes(src):
    if re.match(r'^https?://', src):
        eprint(f"Downloading PDF: {src}")
        return fetch(src, binary=True)
    with open(os.path.expanduser(src), "rb") as f:
        return f.read()


def process_pdf(src, public_dir, teaser, method, figures, text_pages=3, min_px=200):
    import fitz  # PyMuPDF, from the PEP 723 header
    doc = fitz.open(stream=load_pdf_bytes(src), filetype="pdf")
    meta = doc.metadata or {}
    pages_text = [doc[i].get_text() for i in range(min(text_pages, doc.page_count))]

    # Catalog embedded raster images, de-duplicated by xref, filtered by size.
    images, seen = [], set()
    for pno in range(doc.page_count):
        for info in doc.get_page_images(pno, full=True):
            xref = info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                ext = doc.extract_image(xref)
            except Exception:
                continue
            w, h = ext.get("width", 0), ext.get("height", 0)
            if w < min_px or h < min_px:
                continue
            images.append({"id": f"P{len(images)+1}", "figure": None, "page": pno + 1,
                           "caption": f"(embedded image on page {pno+1})", "image_kind": "raster",
                           "has_image": True, "width": w, "height": h,
                           "_xref": xref, "_ext": ext["ext"], "_bytes": ext["image"]})
    # Also offer page-1 render as a teaser candidate (many teasers are vector).
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    images.append({"id": "PAGE1", "figure": None, "page": 1,
                   "caption": "(rendered image of page 1 — teaser candidate)",
                   "image_kind": "raster", "has_image": True, "width": pix.width,
                   "height": pix.height, "_render": pix.tobytes("png")})

    def saver(im, base_url, pdir, stem):
        ext = "." + im.get("_ext", "png") if "_ext" in im else ".png"
        dest = os.path.join(pdir, stem + ext)
        with open(dest, "wb") as f:
            f.write(im.get("_bytes") or im.get("_render"))
        n = os.path.getsize(dest)
        eprint(f"  saved {im['id']} -> {dest} ({n} B)")
        return {"id": im["id"], "figure": None, "saved_as": os.path.basename(dest),
                "path": dest, "bytes": n, "kind": "raster", "src": f"pdf:{src}"}

    saved = do_saves(images, "", public_dir, teaser, method, figures, saver)
    catalog = [{k: v for k, v in im.items() if not k.startswith("_")} for im in images]
    return {"source": "pdf", "pdf_path": src, "pdf_metadata": meta,
            "text_pages": pages_text, "title": meta.get("title", ""),
            "authors": [], "abstract": "", "year": "", "images": catalog,
            "tables": [], "bibtex": build_bibtex("", {"title": meta.get("title", "")}),
            "saved": saved,
            "note": ("PDF mode: title/authors/abstract are NOT auto-parsed — read them "
                     "from text_pages (page 1 usually has title+authors+abstract). Pick the "
                     "teaser/method from `images` by id (P1, P2, … or PAGE1) and re-run with "
                     "--teaser/--method. Tables aren't auto-converted from PDF; transcribe by hand.")}


# ---------------------------------------------------------------------------
# arXiv path
# ---------------------------------------------------------------------------
def process_arxiv(arxiv_in, public_dir, teaser, method, figures):
    arxiv_id = parse_arxiv_id(arxiv_in)
    eprint(f"arXiv id: {arxiv_id}")
    meta = get_metadata(arxiv_id)
    html_url = f"https://arxiv.org/html/{arxiv_id}"
    base_url = html_url + "/"
    eprint(f"Fetching HTML: {html_url}")
    images, tables = [], []
    try:
        fp = FigureTableParser()
        fp.feed(fetch(html_url))
        eprint(f"Found {len(fp.figures)} figures, {len(fp.graphics)} standalone graphics, {len(fp.tables)} tables")
        images = catalog_html_images(fp)
        tables = [t for t in (table_to_ukhtml(t) for t in fp.tables) if t]
    except Exception as e:
        eprint(f"WARN: could not process HTML ({e}). Metadata/bibtex still available; figures/tables skipped.")

    saved = do_saves(images, base_url, public_dir, teaser, method, figures, save_html_image)
    catalog = [{k: v for k, v in im.items() if not k.startswith("_")} for im in images]
    return {"source": "arxiv", "arxiv_id": arxiv_id,
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}", "html_url": html_url, **meta,
            "tl_dr_source": meta["abstract"], "bibtex": build_bibtex(arxiv_id, meta),
            "images": catalog, "tables": tables, "saved": saved}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv", nargs="?", help="arXiv url or id (omit if using --pdf)")
    ap.add_argument("--pdf", help="path or http(s) URL to a PDF (direct-PDF mode)")
    ap.add_argument("--public-dir", default="public")
    ap.add_argument("--out", default="-")
    ap.add_argument("--teaser", default=None, help="image id (or bare Figure N) -> teaser.<ext>")
    ap.add_argument("--method", default="", help="comma list of ids -> method.<ext>, method2.<ext>, …")
    ap.add_argument("--figures", default="", help="comma list of ids -> fig_<id>.<ext>")
    args = ap.parse_args()

    if not args.pdf and not args.arxiv:
        ap.error("provide an arXiv url/id or --pdf")
    os.makedirs(args.public_dir, exist_ok=True)

    if args.pdf:
        result = process_pdf(args.pdf, args.public_dir, args.teaser, args.method, args.figures)
    else:
        result = process_arxiv(args.arxiv, args.public_dir, args.teaser, args.method, args.figures)

    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out == "-":
        print(out)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        eprint(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
