#!/usr/bin/env python3
"""
Generate the public landing page and the QR code that points at it.

The landing page is what a conference attendee lands on after scanning the
QR code on a slide or a handout: a short explanation and one large Download
button that hands them the self-contained pricing-assistant.html.

Outputs:
    index.html          the landing page (QR inlined as SVG, no external refs)
    assets/qr.svg       vector QR, for slides and print
    assets/qr.png       raster QR at ~1000px, for slides and print
    assets/qr-card.svg  QR with caption, sized for a handout / slide corner

Usage:
    python3 build/make_site.py                      # uses the default URL
    python3 build/make_site.py --url https://...    # any other host

The URL is baked into the QR, so if you move the site, re-run this with the
new --url. The landing page also compares the baked URL against the address
it is actually being served from, and shows a loud warning if they differ --
so a stale QR can never quietly end up on a printed handout.
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import segno
except ImportError:
    print("ERROR: segno is not installed.  pip install segno", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TEMPLATE = ROOT / "src" / "index.template.html"
OUT = ROOT / "index.html"

DEFAULT_URL = "https://powersurge91.github.io/Legal-Pricing-Assistant-/"

NAVY = "#1a2b5e"


def _inline_svg(qr, scale, border=4):
    """Inline SVG for the QR, safe to resize with CSS.

    Two things bite here, and both produce a code a camera cannot read:

    * segno's inline SVG carries width/height but NO viewBox. Setting a CSS
      width on it therefore CROPS the symbol instead of scaling it -- a 410px
      symbol shown at 240px loses two of its three finder patterns.
    * border=4 keeps the mandatory 4-module quiet zone inside the image, rather
      than depending on whatever padding the surrounding CSS happens to give.
    """
    svg = qr.svg_inline(scale=scale, border=border, dark=NAVY, light="#ffffff")
    w, h = qr.symbol_size(scale=scale, border=border)
    svg, n = re.subn(
        r"^<svg\b[^>]*>",
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'width="{w}" height="{h}" class="segno">',
        svg, count=1)
    if n != 1:
        raise SystemExit("ERROR: could not rewrite the QR <svg> opening tag")
    if "viewBox" not in svg:
        raise SystemExit("ERROR: QR svg still has no viewBox")
    return svg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL,
                    help=f"public URL of the landing page (default: {DEFAULT_URL})")
    ap.add_argument("--app", default="pricing-assistant.html",
                    help="filename of the self-contained app, relative to the page")
    args = ap.parse_args()

    url = args.url
    if not url.startswith(("http://", "https://")):
        print(f"ERROR: --url must be absolute, got {url!r}", file=sys.stderr)
        sys.exit(1)

    ASSETS.mkdir(exist_ok=True)

    # Error correction level M (~15% recovery) is the usual choice for a
    # printed code: robust enough for a slide photographed from row 20, without
    # inflating the module count the way H would.
    qr = segno.make(url, error="m")
    print(f"  url        {url}")
    print(f"  qr         version {qr.version}, level {qr.error.upper()}, "
          f"{qr.symbol_size(border=0)[0]}x{qr.symbol_size(border=0)[0]} modules")

    qr.save(ASSETS / "qr.svg", scale=10, border=4, dark=NAVY, light="#ffffff")
    qr.save(ASSETS / "qr.png", scale=24, border=4, dark=NAVY, light="#ffffff")
    print(f"  wrote      assets/qr.svg  ({(ASSETS/'qr.svg').stat().st_size:,} bytes)")
    print(f"  wrote      assets/qr.png  ({(ASSETS/'qr.png').stat().st_size:,} bytes)")

    # A captioned version, ready to drop straight onto a slide.
    _write_qr_card(qr, url)
    print(f"  wrote      assets/qr-card.svg  ({(ASSETS/'qr-card.svg').stat().st_size:,} bytes)")

    # Inline SVG for the landing page itself, so the page has no external refs.
    inline_svg = _inline_svg(qr, scale=10)

    if not TEMPLATE.exists():
        print(f"ERROR: missing template {TEMPLATE}", file=sys.stderr)
        sys.exit(1)
    html = TEMPLATE.read_text(encoding="utf-8")

    app_size = 0
    app_path = ROOT / args.app
    if app_path.exists():
        app_size = app_path.stat().st_size
    else:
        print(f"  WARNING: {args.app} not found -- run build/inline.py first")

    subs = {
        "__APP_URL__": url,
        "__APP_FILE__": args.app,
        "__APP_SIZE__": f"{app_size / 1048576:.1f} MB" if app_size else "--",
        "__QR_SVG__": inline_svg,
    }
    for key, val in subs.items():
        if key not in html:
            print(f"ERROR: template is missing placeholder {key}", file=sys.stderr)
            sys.exit(1)
        html = html.replace(key, val)

    leftovers = re.findall(r'\b(?:src|href)\s*=\s*["\'](https?://[^"\']+)["\']', html, re.I)
    external = [u for u in leftovers if u != url]
    if external:
        print("ERROR: landing page has external references:\n  " + "\n  ".join(external),
              file=sys.stderr)
        sys.exit(1)

    OUT.write_text(html, encoding="utf-8")
    print(f"  wrote      index.html  ({len(html):,} bytes)")


def _write_qr_card(qr, url):
    """QR plus a caption, on a white card -- drop-in for a slide or handout."""
    body = _inline_svg(qr, scale=8)
    size = qr.symbol_size(scale=8, border=4)[0]
    pad, cap = 12, 96
    w = size + pad * 2
    h = size + pad + cap
    card = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <rect width="{w}" height="{h}" fill="#ffffff"/>
  <rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" fill="none" stroke="#dde0eb"/>
  <g transform="translate({pad},{pad})">{body}</g>
  <text x="{w/2}" y="{size + pad + 34}" text-anchor="middle"
        font-family="Arial, Helvetica, sans-serif" font-size="19" font-weight="700"
        fill="{NAVY}">Pricing Assistant</text>
  <text x="{w/2}" y="{size + pad + 58}" text-anchor="middle"
        font-family="Arial, Helvetica, sans-serif" font-size="13"
        fill="#5b6480">Scan to download &#183; works offline</text>
  <text x="{w/2}" y="{size + pad + 78}" text-anchor="middle"
        font-family="Arial, Helvetica, sans-serif" font-size="10"
        fill="#8a91a6">{url}</text>
</svg>
'''
    (ASSETS / "qr-card.svg").write_text(card, encoding="utf-8")


if __name__ == "__main__":
    main()
