# Pricing Assistant

A legal matter pricing tool that runs entirely in the browser, as a **single
self-contained HTML file**. No install, no server, no account, no network — you
can open it from a USB stick on a plane and every feature still works.

Built by Sergey Mezhiritskiy.

**Live page:** https://powersurge91.github.io/Legal-Pricing-Assistant-/

---

## What's here

| Path | What it is |
|---|---|
| `pricing-assistant.html` | **The deliverable.** The self-contained app — this is the file people download. Generated; do not hand-edit. |
| `index.html` | The public landing page: description, download button, QR code. Generated. |
| `assets/qr.*` | QR code pointing at the landing page — PNG and SVG for slides, plus a captioned card. Generated. |
| `src/pricing-assistant.src.html` | **The source you edit.** Loads its libraries from CDNs; the build inlines them. |
| `src/index.template.html` | Source template for the landing page. |
| `build/inline.py` | Builds `pricing-assistant.html` from the source. |
| `build/make_site.py` | Builds `index.html` and the QR assets. |
| `build/vendor/` | The five pinned libraries, vendored so builds are reproducible and need no network. |

Everything at the repo root is **generated**. Edit `src/`, then rebuild.

## Rebuilding

```bash
python3 build/inline.py      # src/pricing-assistant.src.html -> pricing-assistant.html
python3 build/make_site.py   # -> index.html + assets/qr.*
```

`make_site.py` needs [segno](https://pypi.org/project/segno/) (`pip install segno`).
`inline.py` has no dependencies beyond the standard library.

If the site ever moves to a different URL, regenerate the QR so it points to the
right place:

```bash
python3 build/make_site.py --url https://example.com/pricing/
```

The landing page compares the URL baked into the QR against the address it is
actually served from, and shows a visible warning if they differ — so a stale QR
can't quietly end up on a printed handout.

## How the offline build works

The source file pulls five libraries from public CDNs. Any one of them failing
to load — no wifi, a blocked CDN, a captive portal at a conference venue —
silently breaks import or export. The build inlines all five:

| Library | Version | Used for |
|---|---|---|
| xlsx-js-style | 1.2.0 | rate-card `.xlsx` import/export |
| pdf.js | 3.4.120 | rate-card `.pdf` import |
| jsPDF | 2.5.1 | `.pdf` export |
| jsPDF-AutoTable | 3.5.31 | table layout in the PDF export |

Four go straight into `<script>` tags. The fifth, the pdf.js **worker**, can't —
pdf.js hands it to the browser as a URL. The build parks it in a non-executing
`<script type="javascript/worker">` block and converts it to a Blob URL at
runtime, which keeps it inside the single file.

The build also patches one thing that offline use would otherwise break: the
"save updated rates back into the app file" fallback read the app's own source
via `fetch(location.href)`, which browsers block on `file://` URLs. It now falls
back to a file picker, so the feature works from a local file too.

`inline.py` fails the build if any external `src`/`href` survives, so the
self-contained guarantee is checked rather than assumed.

## Updating rate data

Two ways:

- **In the app** — the Settings panel writes new rates back into the file.
- **By hand** — open the `.html` in a text editor, find `// ── BEGIN RATE DATA ──`,
  replace the array, and bump `RATE_DATA_VERSION`. Do this in
  `src/pricing-assistant.src.html` and rebuild, so the change survives the next build.

## Publishing

GitHub Pages, deploying from the `main` branch root. `.nojekyll` is present so
the asset paths are served verbatim.

> **Note:** GitHub Pages on a **private** repo requires a paid plan. On the free
> plan the repository must be public for the download link to work.

## Privacy

The app runs wholly in the browser. It makes no network requests — the build
enforces that — and nothing a user loads into it leaves their device.
