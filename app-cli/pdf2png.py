#!/usr/bin/env python3
"""
pdf2png.py – Rasterise PDF pages to PNG so they can be viewed inline.

Handy for looking at PDFs produced by the Streamlit app or by app-cli.py
(`--pdf`) without opening an external viewer.

Usage
-----
    python pdf2png.py report.pdf                 # every page → report_p1.png …
    python pdf2png.py report.pdf -d 140          # higher resolution
    python pdf2png.py report.pdf -p 1 -p 2       # only pages 1 and 2
    python pdf2png.py report.pdf -o /tmp/out     # choose output folder
    python pdf2png.py *.pdf                      # several files
    python pdf2png.py report.pdf -q              # paths only

Each PNG path is printed on its own line, followed by a markdown image link
that chat front-ends (OpenCode) can render.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

try:
    import pymupdf
except ImportError:                                  # pragma: no cover
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("pymupdf is required:  pip install pymupdf")


def pdf_to_png(pdf_path: str, out_dir: str | None = None, dpi: int = 100,
               pages: list[int] | None = None) -> list[str]:
    """Render pages of `pdf_path` to PNG files; return the paths written."""
    pdf_path = os.path.abspath(os.path.expanduser(pdf_path))
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(pdf_path)

    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    target = os.path.abspath(out_dir) if out_dir else \
        os.path.join(os.path.dirname(pdf_path), f'{stem}_png')
    os.makedirs(target, exist_ok=True)

    written: list[str] = []
    zoom = dpi / 72.0
    with pymupdf.open(pdf_path) as doc:
        wanted = range(doc.page_count) if not pages else \
            [p - 1 for p in pages if 1 <= p <= doc.page_count]
        for i in wanted:
            pix = doc.load_page(i).get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            path = os.path.join(target, f'{stem}_p{i + 1}.png')
            pix.save(path)
            written.append(path)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Rasterise PDF pages to PNG.')
    ap.add_argument('pdf', nargs='+', help='PDF file(s); shell expands globs')
    ap.add_argument('-o', '--out-dir', help='output folder (default <pdf>_png next to the PDF)')
    ap.add_argument('-d', '--dpi', type=int, default=100, help='resolution (default 100)')
    ap.add_argument('-p', '--page', type=int, action='append', dest='pages',
                    help='page to render, 1-based (repeatable; default all)')
    ap.add_argument('-q', '--quiet', action='store_true', help='print paths only')
    ap.add_argument('-t', '--text', action='store_true',
                    help='also print the extracted text of each page')
    args = ap.parse_args(argv)

    files: list[str] = []
    for pattern in args.pdf:
        files.extend(glob.glob(pattern) or [pattern])

    rc = 0
    for path in files:
        try:
            if args.text:
                print(f"===== {path} =====")
                with pymupdf.open(path) as doc:
                    for i, page in enumerate(doc, 1):
                        print(f"----- page {i} -----")
                        print(page.get_text().strip())
            for png in pdf_to_png(path, args.out_dir, args.dpi, args.pages):
                print(png)
                if not args.quiet:
                    print(f"![{os.path.splitext(os.path.basename(png))[0]}]({png})")
        except Exception as e:
            print(f"❌ {path}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
