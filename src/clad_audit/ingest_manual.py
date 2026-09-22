"""Stage 4c — ingest manually retrieved full text into the pipeline.

PDFs pulled by hand through institutional access land in data/fulltext_manual/<pmid>.pdf.
The pipeline only reads data/fulltext/, so they are invisible to extract.py until staged here.

COPIES (never moves): fulltext_manual/ stays the pristine hand-curated source, so a re-run is
always safe and manual work can't be destroyed by a pipeline bug.

Records provenance in data/fulltext_provenance.csv. This matters beyond bookkeeping: the
fetch-tier sensitivity analysis asks whether reporting completeness differs between
openly-retrieved and paywall-recovered studies. Manual institutional retrievals are the most
paywalled slice of all, so they must stay identifiable rather than melting into data/fulltext/.

Validates before staging — a scanned PDF with no text layer would extract as silent garbage:
  * filename stem must be a PMID present in corpus_routed.csv
  * must open as a PDF and carry >= MIN_CHARS of extractable text
  * never overwrites an existing data/fulltext/<pmid>.* (first route to land wins)

    uv run python -m clad_audit.ingest_manual --dry-run    # report only, touch nothing
    uv run python -m clad_audit.ingest_manual              # stage + record provenance
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import shutil

import fitz  # pymupdf

from .config import DATA_DIR

FULLTEXT_DIR = DATA_DIR / "fulltext"
MANUAL_DIR = DATA_DIR / "fulltext_manual"
ROUTED_CSV = DATA_DIR / "corpus_routed.csv"
PROVENANCE = DATA_DIR / "fulltext_provenance.csv"

MIN_CHARS = 500          # below this a PDF is an image scan, not a text layer
ROUTE = "manual_institutional"


def _text_chars(path) -> tuple[int, int]:
    """(pages, extractable characters). Raises if the file will not open as a PDF."""
    doc = fitz.open(path)
    try:
        return doc.page_count, sum(len(pg.get_text()) for pg in doc)
    finally:
        doc.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only; copy nothing")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    args = ap.parse_args()

    if not MANUAL_DIR.exists():
        print(f"nothing to do: {MANUAL_DIR} does not exist")
        return

    corpus = {r["pmid"] for r in csv.DictReader(ROUTED_CSV.open())}
    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in FULLTEXT_DIR.iterdir() if p.is_file()}
    already = {r["pmid"] for r in csv.DictReader(PROVENANCE.open())} if PROVENANCE.exists() else set()

    staged, skipped = [], []
    for p in sorted(MANUAL_DIR.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        pmid = p.stem
        if p.suffix.lower() != ".pdf":
            skipped.append((pmid, "not a .pdf")); continue
        if pmid not in corpus:
            skipped.append((pmid, "pmid not in corpus_routed.csv")); continue
        if pmid in existing:
            skipped.append((pmid, "already in data/fulltext (kept existing)")); continue
        try:
            pages, chars = _text_chars(p)
        except Exception as e:  # noqa: BLE001 — corrupt/encrypted PDF
            skipped.append((pmid, f"unreadable: {type(e).__name__}")); continue
        if chars < args.min_chars:
            skipped.append((pmid, f"no text layer ({chars} chars, {pages}p) — needs OCR")); continue
        staged.append((pmid, p, pages, chars))

    print(f"scanned {MANUAL_DIR}: {len(staged)} to stage, {len(skipped)} skipped")
    for pmid, why in skipped:
        print(f"  skip {pmid:>9}  {why}")

    if args.dry_run:
        print("\n--dry-run: nothing copied.")
        return

    new_prov = not PROVENANCE.exists()
    stamp = dt.date.today().isoformat()
    with PROVENANCE.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new_prov:
            w.writerow(["pmid", "route", "source_file", "pages", "text_chars", "staged_on"])
        for pmid, src, pages, chars in staged:
            shutil.copy2(src, FULLTEXT_DIR / f"{pmid}.pdf")
            if pmid not in already:
                w.writerow([pmid, ROUTE, src.name, pages, chars, stamp])

    total = len([p for p in FULLTEXT_DIR.iterdir() if p.is_file()])
    print(f"\nstaged {len(staged)} PDFs -> {FULLTEXT_DIR}")
    print(f"provenance: {PROVENANCE}")
    print(f"full text on disk now: {total}")
    print("\nnext: regenerate the worklist, then extract:")
    print("  Rscript -e 'source(\"analysis/_retrieval_worklist.R\")'")
    print("  uv run python -m clad_audit.extract --limit 5     # pilot before the full run")


if __name__ == "__main__":
    main()
