"""Render a Markdown file to PDF (Markdown -> HTML -> headless Edge/Chrome print).

This is how the docs/*.pdf files are produced.

Usage:
    python tools/md_to_pdf.py docs/X.md [docs/X.pdf]

Needs:
    - Python package `markdown`  (python -m pip install markdown)
    - Microsoft Edge or Google Chrome installed (override the executable with
      the environment variable MD_TO_PDF_BROWSER).

A temporary HTML file is written next to the Markdown file (so relative image
links resolve) and deleted afterwards. If the output path is omitted, the PDF
is written next to the Markdown file with a .pdf extension.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

BROWSERS = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
]

CSS = """
@page { size: A4; margin: 18mm; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       font-size: 9pt; line-height: 1.4; color: #1f2328; }
h1, h2, h3, h4 { font-weight: 600; line-height: 1.25; margin: 1.3em 0 0.5em; }
h1 { font-size: 20pt; border-bottom: 1px solid #d0d7de; padding-bottom: .3em; margin-top: 0; }
h2 { font-size: 15pt; border-bottom: 1px solid #d0d7de; padding-bottom: .3em; }
h3 { font-size: 12.5pt; }
h4 { font-size: 11pt; }
p, ul, ol { margin: 0 0 0.8em; }
table { border-collapse: collapse; width: 100%; table-layout: auto; font-size: 8pt; margin: 0 0 1em; }
td, th { border: 1px solid #d0d7de; padding: 4px 8px; vertical-align: top; word-break: break-word; }
th { background: #f6f8fa; text-align: left; }
code { font-family: Consolas, "SFMono-Regular", Menlo, monospace; font-size: 90%;
       background: #eff1f3; padding: 0.15em 0.35em; border-radius: 4px; }
pre { background: #f6f8fa; padding: 10px 12px; border-radius: 6px; font-size: 8pt;
      white-space: pre-wrap; word-break: break-word; }
pre code { background: none; padding: 0; font-size: inherit; }
img { max-width: 100%; }
blockquote { margin: 0 0 1em; padding: 0 1em; color: #59636e; border-left: 4px solid #d0d7de; }
hr { border: 0; border-top: 1px solid #d0d7de; margin: 1.5em 0; }
a { color: #0969da; text-decoration: none; }
"""


def find_browser():
    env = os.environ.get("MD_TO_PDF_BROWSER")
    if env:
        return env
    for b in BROWSERS:
        if Path(b).exists():
            return b
    sys.exit("No Edge/Chrome found; set MD_TO_PDF_BROWSER.")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    md_path = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else md_path.with_suffix(".pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    body = markdown.markdown(
        md_path.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    html = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{md_path.stem}</title><style>{CSS}</style></head>'
            f'<body>{body}</body></html>')
    tmp_html = md_path.parent / f".{md_path.stem}.md2pdf.tmp.html"
    tmp_html.write_text(html, encoding="utf-8")
    profile = Path(tempfile.gettempdir()) / "md2pdf_profile"
    try:
        if out.exists():
            out.unlink()
        cmd = [find_browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
               f"--user-data-dir={profile}", f"--print-to-pdf={out}", tmp_html.as_uri()]
        subprocess.run(cmd, check=True, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        tmp_html.unlink(missing_ok=True)
        shutil.rmtree(profile, ignore_errors=True)
    if not out.exists() or out.stat().st_size < 10_000:
        sys.exit(f"PDF missing or too small: {out}")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
