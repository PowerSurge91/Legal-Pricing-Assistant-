#!/usr/bin/env python3
"""
Build a fully self-contained, offline-capable single-file build of the
Pricing Assistant.

Takes src/pricing-assistant.src.html (which loads five libraries from public
CDNs) and produces pricing-assistant.html with every one of those libraries
inlined, so the file works with no network connection at all -- opened
straight off a USB stick, a Downloads folder, or an airplane tray table.

What gets inlined
-----------------
  xlsx-js-style 1.2.0              rate-card .xlsx import/export
  pdf.js 3.4.120 (main)            rate-card .pdf import
  pdf.js 3.4.120 (worker)          -- as a Blob URL, see below
  jsPDF 2.5.1                      .pdf export
  jsPDF-AutoTable 3.5.31           table layout in the .pdf export

The worker is the awkward one: pdf.js hands its worker script to the browser
by URL, so it cannot simply be a <script> tag. It is parked in a non-executing
<script type="javascript/worker"> block and turned into a Blob URL at runtime,
which keeps it inside the single file.

Also patched: the "save rate data back to the app file" fallback, which read
the app's own source via fetch(location.href). That is blocked on file://
URLs, so offline users on Firefox/Safari would hit a dead end. It now falls
back to a file picker.

Usage:  python3 build/inline.py
"""

import re
import sys
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "pricing-assistant.src.html"
VENDOR = ROOT / "build" / "vendor"
OUT = ROOT / "pricing-assistant.html"

# CDN URL -> vendored file. Versions match the original tags exactly; these
# files came from the npm packages the CDNs themselves publish.
SCRIPTS = [
    ("https://cdn.jsdelivr.net/npm/xlsx-js-style@1.2.0/dist/xlsx.bundle.js",
     "xlsx.bundle.js", "xlsx-js-style 1.2.0"),
    ("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.4.120/pdf.min.js",
     "pdf.min.js", "pdf.js 3.4.120"),
    ("https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js",
     "jspdf.umd.min.js", "jsPDF 2.5.1"),
    ("https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js",
     "jspdf.plugin.autotable.min.js", "jsPDF-AutoTable 3.5.31"),
]

WORKER_URL = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.4.120/pdf.worker.min.js"
WORKER_FILE = "pdf.worker.min.js"


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def read_lib(name):
    p = VENDOR / name
    if not p.exists():
        die(f"missing vendored library: {p}")
    text = p.read_text(encoding="utf-8")
    # A literal </script> anywhere inside would terminate the host <script>
    # block early and corrupt the page. None of the pinned versions contain
    # one, but a version bump could, so fail loudly rather than ship a
    # silently broken file.
    if re.search(r"</\s*script", text, re.I):
        die(f"{name} contains a '</script' sequence and cannot be inlined as-is")
    return text


def main():
    if not SRC.exists():
        die(f"missing source: {SRC}")
    html = SRC.read_text(encoding="utf-8")
    original_len = len(html)

    # ---- 1. Inline the four regular <script src=...> tags --------------
    for url, fname, label in SCRIPTS:
        tag = re.compile(
            r'<script[^>]*\bsrc\s*=\s*["\']' + re.escape(url) + r'["\'][^>]*>\s*</script>',
            re.I,
        )
        if not tag.search(html):
            die(f"could not find the <script> tag for {label} ({url})")
        code = read_lib(fname)
        block = (
            f"<!-- {label} - inlined for offline use (was: {url}) -->\n"
            f"<script>\n{code}\n</script>"
        )
        html = tag.sub(lambda _m, b=block: b, html, count=1)
        print(f"  inlined  {label:<28} {len(code):>9,} bytes")

    # ---- 2. Inline the pdf.js worker as a Blob URL ---------------------
    worker = read_lib(WORKER_FILE)
    worker_block = (
        f"<!-- pdf.js 3.4.120 worker - inlined for offline use (was: {WORKER_URL}) -->\n"
        '<script id="pdfjs-worker-src" type="javascript/worker">\n'
        f"{worker}\n"
        "</script>"
    )
    # Park it immediately after the pdf.js main script so it is in the DOM
    # before any code reaches for it.
    anchor = "<!-- pdf.js 3.4.120 - inlined for offline use"
    idx = html.find(anchor)
    if idx < 0:
        die("could not find the inlined pdf.js block to anchor the worker to")
    end = html.find("</script>", idx)
    if end < 0:
        die("malformed inlined pdf.js block")
    end += len("</script>")
    html = html[:end] + "\n" + worker_block + html[end:]
    print(f"  inlined  {'pdf.js worker':<28} {len(worker):>9,} bytes")

    # Point pdf.js at the Blob instead of the CDN.
    worker_assign = re.compile(
        r"pdfjsLib\.GlobalWorkerOptions\.workerSrc\s*=\s*['\"]"
        + re.escape(WORKER_URL)
        + r"['\"]\s*;"
    )
    if not worker_assign.search(html):
        die("could not find the pdfjsLib.GlobalWorkerOptions.workerSrc assignment")
    replacement = (
        "pdfjsLib.GlobalWorkerOptions.workerSrc = (function(){\n"
        "      // Offline build: the worker lives in this file. Hand pdf.js a Blob\n"
        "      // URL for it rather than a CDN URL. Built once and reused.\n"
        "      if (window.__pdfWorkerBlobUrl) return window.__pdfWorkerBlobUrl;\n"
        "      var el = document.getElementById('pdfjs-worker-src');\n"
        "      if (!el) throw new Error('Embedded pdf.js worker is missing from this file.');\n"
        "      var blob = new Blob([el.textContent], {type: 'application/javascript'});\n"
        "      window.__pdfWorkerBlobUrl = URL.createObjectURL(blob);\n"
        "      return window.__pdfWorkerBlobUrl;\n"
        "    })();"
    )
    html = worker_assign.sub(lambda _m: replacement, html, count=1)
    print("  rewired  pdf.js workerSrc -> Blob URL")

    # ---- 3. Make the self-save fallback work on file:// -----------------
    # fetch(location.href) throws on file:// (opaque origin), which would
    # strand offline users whose browser lacks showOpenFilePicker.
    old_fetch = (
        "    let currentText;\n"
        "    try { currentText = await fetch(location.href, {cache:'no-store'}).then(r=>r.text()); }\n"
        "    catch(e) { showToast('Could not read the current app file: ' + e.message); return; }"
    )
    new_fetch = (
        "    let currentText;\n"
        "    try { currentText = await fetch(location.href, {cache:'no-store'}).then(r=>r.text()); }\n"
        "    catch(e) {\n"
        "      // Offline build: fetch() of location.href is blocked on file:// URLs,\n"
        "      // so ask the user to hand us the file instead.\n"
        "      showToast('Select this app\\u2019s .html file so the new rates can be written into a copy.');\n"
        "      try { currentText = await readAppFileViaPicker(); }\n"
        "      catch(err) { if (err && err.message === 'cancelled') return;\n"
        "                   showToast('Could not read the app file: ' + err.message); return; }\n"
        "    }"
    )
    if old_fetch not in html:
        die("could not find the fetch(location.href) fallback to patch")
    html = html.replace(old_fetch, new_fetch, 1)

    # The <input type=file> helper the patch above calls.
    helper = """
// Offline build helper: read this app's own .html via a file picker, for
// browsers where fetch(location.href) is unavailable (file:// URLs).
function readAppFileViaPicker() {
  return new Promise((resolve, reject) => {
    const input = Object.assign(document.createElement('input'),
      { type: 'file', accept: '.html,text/html' });
    input.style.cssText = 'position:fixed;left:-9999px;top:0;';
    let settled = false;
    input.addEventListener('change', () => {
      settled = true;
      const file = input.files && input.files[0];
      input.remove();
      if (!file) { reject(new Error('cancelled')); return; }
      const reader = new FileReader();
      reader.onload  = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error('could not read the selected file'));
      reader.readAsText(file);
    });
    // 'cancel' is not universally supported; the focus fallback covers the rest.
    input.addEventListener('cancel', () => {
      settled = true; input.remove(); reject(new Error('cancelled'));
    });
    window.addEventListener('focus', () => {
      setTimeout(() => {
        if (!settled) { settled = true; input.remove(); reject(new Error('cancelled')); }
      }, 800);
    }, { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

// Shared writer: takes a transform(currentText)->newText|null"""
    anchor2 = "\n// Shared writer: takes a transform(currentText)->newText|null"
    if anchor2 not in html:
        die("could not find the writeAppFile anchor comment")
    html = html.replace(anchor2, "\n" + helper.strip("\n"), 1)
    print("  patched  self-save fallback for file:// URLs")

    # ---- 4. Verify nothing external is FETCHED ---------------------------
    # The point of the offline guarantee is that opening the file makes no
    # network request. That means no external src=, no stylesheet <link>, no
    # @import. A plain <a href> is not a fetch -- it is inert until somebody
    # clicks it, and the author's profile link is deliberately one of those.
    leftovers = set()
    for m in re.finditer(r'\bsrc\s*=\s*["\'](https?://[^"\']+)["\']', html, re.I):
        leftovers.add("src: " + m.group(1))
    for tag in re.finditer(r'<link\b[^>]*>', html, re.I):
        for m in re.finditer(r'href\s*=\s*["\'](https?://[^"\']+)["\']', tag.group(0), re.I):
            leftovers.add("link: " + m.group(1))
    for m in re.finditer(r"@import\s+url\(\s*['\"]?(https?://[^'\")]+)", html, re.I):
        leftovers.add("@import: " + m.group(1))
    if leftovers:
        die("external references that would be fetched remain:\n  " + "\n  ".join(sorted(leftovers)))

    anchors = sorted({m.group(1) for m in
                      re.finditer(r'<a\b[^>]*\bhref\s*=\s*["\'](https?://[^"\']+)["\']', html, re.I)})

    OUT.write_text(html, encoding="utf-8")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()

    print()
    print(f"  source   {original_len:>10,} bytes")
    print(f"  output   {len(html):>10,} bytes  ->  {OUT.relative_to(ROOT)}")
    print(f"  sha256   {digest}")
    print("  nothing external is fetched")
    for a in anchors:
        print(f"  outbound link (inert until clicked)  {a}")


if __name__ == "__main__":
    main()
