---
name: arxiv-to-projectpage
description: >-
  Fill in this repo's project-page `template.yaml` from a paper. Use this
  whenever the user gives an arXiv link or id (arxiv.org/abs/..., /html/...,
  /pdf/..., or a bare id like 2312.02008) OR a direct PDF (a local file or a
  .pdf URL) and wants a project page, teaser, paper page, or template.yaml
  populated — even if they only paste the URL and say "make a project page" or
  "fill the template". It pulls the title, authors, and abstract, downloads the
  teaser and method figures into `public/`, writes a TL;DR, and converts the
  paper's TeX tables into the UIKit HTML tables the template expects.
compatibility: >-
  Runs scripts/fetch_arxiv.py through uv (PEP 723 inline deps). Requires `pixi`
  with the `uv` dependency (already in pixi.toml); no manual pip installs.
  Network access to arxiv.org for arXiv input.
---

# Paper → project page template.yaml

This skill turns a paper into a filled-in `template.yaml` for the omron-sinicx
project-page template. `scripts/fetch_arxiv.py` does the deterministic work —
fetching metadata, downloading the right images, converting tables. Your job is
the judgment it can't do: choosing the teaser, writing a crisp TL;DR, and
slotting the content into the template's structure while preserving everything
the paper doesn't touch.

## Running the script (uv / PEP 723)

The script declares its own dependencies in a PEP 723 header, so **always run it
through uv** — never `python3` it directly:

```bash
pixi run uv run .claude/skills/arxiv-to-projectpage/scripts/fetch_arxiv.py <args>
```

uv reads the header and provides the one dependency (PyMuPDF, used only for the
PDF path). The arXiv path is pure stdlib, so the first run is quick.

## Two input modes

- **arXiv** (preferred when available): metadata from the arXiv API (clean,
  structured), figures/tables from the rendered HTML (`arxiv.org/html/<id>`).
- **Direct PDF** (`--pdf <path-or-url>`): for papers not on arXiv, or when the
  user hands you a PDF. PyMuPDF extracts the first pages of text and the
  embedded images. There's no clean metadata or table markup in a PDF, so you
  parse the title/authors/abstract from the text yourself (page 1 has them).

Pick arXiv if you have an id/link; use `--pdf` only when that's all you've got.

## Workflow

### 1. List the paper's contents (no downloads yet)

Use a **per-paper output path** so parallel runs don't clobber each other:

```bash
# arXiv
pixi run uv run .claude/skills/arxiv-to-projectpage/scripts/fetch_arxiv.py \
  "<arxiv-url-or-id>" --out /tmp/paper-<arxiv-id>.json
# or a direct PDF
pixi run uv run .claude/skills/arxiv-to-projectpage/scripts/fetch_arxiv.py \
  --pdf "<path-or-url>" --out /tmp/paper-<name>.json
```

Read the JSON.

- **arXiv** gives `title`, `authors`, `abstract`, `year`, a ready `bibtex`, an
  `images` catalog, and `tables` with pre-converted UIKit HTML.
- **PDF** gives `text_pages` (read title/authors/abstract from `text_pages[0]`),
  an `images` catalog, and an empty `tables` (transcribe tables by hand from the
  paper if the user wants them).

Every selectable image has a stable **`id`**:

| id            | meaning                                                                         |
| ------------- | ------------------------------------------------------------------------------- |
| `F1`, `F2`, … | arXiv figures (in document order); `figure` field = the real "Figure N" or null |
| `G1`, `G2`, … | uncaptioned graphics near the top of an arXiv paper (often the true teaser)     |
| `P1`, `P2`, … | images embedded in a PDF                                                        |
| `PAGE1`       | a rendered image of the PDF's first page (teaser fallback)                      |

`image_kind` is `raster` (downloadable), `svg` (inline vector, saved as `.svg`),
or `none` (a placeholder the HTML didn't inline). Only `has_image: true` images
can be saved.

### 2. Choose the teaser and method figures — from the captions

This is the one editorial step. Read the captions and pick:

- **Teaser**: the single image that best sells the paper. Usually the
  lowest-numbered figure whose caption reads like an overview or headline result
  ("overview", "given a collection of…", "we propose", qualitative samples).
  Figure 1 is the common choice — but check `has_image`: **Figure 1 sometimes has
  `image_kind: none`** (a composite the HTML didn't inline). When that happens,
  use a `G*` uncaptioned graphic if present, else the next figure with an image,
  and say which you used. Prefer `raster` over `svg` for the teaser since it's
  also the social/OGP card; `svg` is fine for in-body method figures.
- **Method figure(s)**: one or two figures of the architecture / approach —
  captions with "framework", "architecture", "overview", "our model", "pipeline".

If nothing suitable has an image, say so and leave the teaser as-is — tell the
user to drop a `public/teaser.png` in manually.

### 3. Download the chosen images

Select by **id** (a bare integer also works as arXiv "Figure N"):

```bash
pixi run uv run .claude/skills/arxiv-to-projectpage/scripts/fetch_arxiv.py \
  "<arxiv-url-or-id>" --public-dir public --teaser F1 --method F2,F3 \
  --out /tmp/paper-<arxiv-id>.json
```

This saves `public/teaser.<ext>`, `public/method.<ext>`, `public/method2.<ext>`
(extensions preserved). The JSON's `saved` block echoes the real filenames — use
those exact names in the YAML, because a jpg teaser is saved as `teaser.jpg`.
Selecting by id matters: figures LaTeXML split into subcaptions come back with
`figure: null` and can only be reached by their `F*` id, not by a number.

If a saved image is very large (say >2 MB), mention it — the user may want to
downsize it for page speed — but don't block on it.

### 4. Fill in template.yaml

Edit `template.yaml` **in place**. Fill what the paper gives you; leave
repo-specific fields alone.

- `title` — the paper title (keep LaTeX like `$\pi_0$` so KaTeX renders it).
- `resources.paper` — the `abs_url` (arXiv) or the PDF/paper URL.
- `description` — a **1–2 sentence TL;DR you write** (not the raw abstract). This
  is the OGP/Twitter text and the page's one-line hook: problem, what's new,
  result. ~30 words, concrete and plain.
- `image` / `url` — leave the `${your-repository-name}` placeholders unless the
  user gives the repo name; the teaser _filename_ still goes in `teaser`.
- `teaser` — the saved teaser filename (`teaser.png` / `teaser.jpg` / `teaser.svg`).
- `authors` — one entry per author, in order (see note below).
- `bibtex` — use the `bibtex` from the JSON (block scalar with `>`).
- `overview` — the abstract, lightly cleaned (drop a leading "Abstract"). A TL;DR
  sentence up front is fine; stay faithful — don't invent claims.
- `body` — see structure below.

**Authors**: the arXiv API (and PDF text) give names only. Write each as
`- name: <full name>` with `affiliation: [1]` as a safe default and no
`url`/`position`. Real affiliations, positions, and homepage URLs are things
only the user knows — fill names, then flag these for a human pass. Don't
fabricate the `affiliations:` list, `conference`, `resources.code`, `video`, or
`contact_ids`.

**Preserve vs. purge — an important distinction.** The template ships pre-filled
with a _different_ paper's data (the MULTIPOLAR example). Two kinds of fields:

- **Repo/venue-generic — preserve**: `theme`, `organization`, `twitter`,
  `speakerdeck`, `header`, `projects`, `meta`. Leave these exactly as-is unless
  the user asks otherwise.
- **Paper-specific — replace or clear, never leave stale**: `title`, `authors`,
  `description`, `overview`, `bibtex`, `teaser`, `resources.*`
  (paper/code/video/blog/demo/huggingface), `conference`. If the new paper
  doesn't supply one (e.g. no code repo yet), **clear it and add a `TODO(human)`
  marker** rather than leaving the old paper's link — a stale
  `code: github.com/…/multipolar` on a different paper's page is a real bug.

#### Body structure

Replace the demo `body` sections with real content. A paper page typically wants
an Overview, a Method section (with the method figure), and a Results section
(with the converted table). Match the reference layout at
`https://omron-sinicx.github.io/mabr/` (Overview → Video → Method → Results):

```yaml
body:
  - title: Method
    text: |
      <one or two paragraphs summarizing the approach, in your words>

      <img src="method.png" alt="" />
      <span class="uk-text-meta">Figure N: <the figure's caption></span>
  - title: Results
    text: |
      <a sentence framing the main result>

      #### <Table caption, shortened>
      <paste tables[i].html from the JSON here, indented to the block scalar>
```

Figures are referenced as `<img src="method.png" />` (files resolve from
`public/`), captions use `<span class="uk-text-meta">`, and tables use the
`uk-table` HTML the script produced — paste it verbatim. Keep the `|`
block-scalar indentation consistent or the YAML won't parse.

### 5. Verify

```bash
pixi run uv run --with pyyaml python -c "import yaml,sys; yaml.safe_load(open('template.yaml')); print('yaml ok')"
ls -la public/ | grep -E 'teaser|method'
```

(`pixi run dev` building cleanly is an equally good check.) Then summarize for
the user: what you filled, which images you chose and why, and the fields that
need a human pass (affiliations, positions, author URLs, conference, code/video).

## Table conversion notes

The script converts each `<table class="ltx_tabular">` into the template's
`uk-table` HTML (overflow wrapper, small/divider classes, `<thead>`/`<tbody>`,
`<b>` for bold cells, `colspan`/`rowspan` preserved, leading bold rows folded
into the header, and math taken from the TeX annotation so `x^{2}` becomes
`x<sup>2</sup>` instead of duplicated text). For a genuinely gnarly table
(deeply nested multirow headers), compare against the paper's HTML table and fix
cells by hand, following the HTML table example already in `template.yaml`.

## Robustness notes

- **Versioned ids**: `2312.02008v1` and `2312.02008` both work.
- **No HTML render**: old or opted-out papers may lack `arxiv.org/html/<id>`
  (the script still returns metadata + bibtex; figures/tables come back empty).
  Fall back to `--pdf https://arxiv.org/pdf/<id>` to get images, or tell the user
  figures need manual adding.
- **PDF tables**: not auto-converted — transcribe from the paper into the
  `uk-table` HTML pattern by hand if the user wants a results table.
- **Idempotent**: re-running save mode overwrites `teaser.*`/`method.*`.
