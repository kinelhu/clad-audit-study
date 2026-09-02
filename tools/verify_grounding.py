"""verify_grounding.py — does every evidence quote actually appear in the paper it came from?

The extraction protocol requires a verbatim supporting quote for any non-zero item score, and the
manuscript calls the audit "evidence-grounded". What the pipeline ENFORCED, however, was only that the
model returned a NON-EMPTY quote string (extract.py checks `.strip() != ""`). Nothing ever checked the
quote against the source, so a fluent fabrication would have passed. This script supplies the missing
check, after the fact, over the whole analyzable cohort.

Method. For each paper, load the text the model was actually shown -- the same paper_text() the pipeline
used, truncated at the same MAX_CHARS -- and ask whether each quote is present. Matching is normalised,
not literal: PDF extraction mangles ligatures, hyphenation, quote marks and column whitespace, so a
strict comparison would fail on faithful quotes and overstate fabrication. A quote counts as grounded if

  1. its normalised form is a substring of the normalised source (EXACT), or
  2. a sliding window of the source reaches >= THRESHOLD character-level similarity (FUZZY).

Anything below that is reported as UNMATCHED -- a quote the paper does not appear to contain.

Usage:  uv run python tools/verify_grounding.py [--sample N] [--threshold 0.85]
Writes analysis/tables/_grounding_audit.csv (one row per quote) and prints the headline rates.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from clad_audit.extract import MAX_CHARS, paper_text  # noqa: E402  (needs the path insert above)

EXTRACT_DIR = ROOT / "data" / "extractions"
OUT = ROOT / "analysis" / "tables" / "_grounding_audit.csv"

# Ligatures and dash/quote variants that differ between the PDF layer and the model's echo of it. Folding
# these is not leniency about content -- it is undoing a lossy encoding so that the comparison is about
# words rather than typography.
_FOLD = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"', " ": " ", "­": "",
}


def norm(s: str) -> str:
    """Lowercase, fold typographic variants, drop soft hyphens, collapse all whitespace."""
    s = unicodedata.normalize("NFKC", s)
    for a, b in _FOLD.items():
        s = s.replace(a, b)
    s = s.replace("-\n", "").replace("- ", "- ")   # rejoin words hyphenated across a line break
    return re.sub(r"\s+", " ", s).strip().lower()


def best_window_ratio(needle: str, hay: str) -> float:
    """Best character-level similarity of `needle` against any same-length window of `hay`.

    Anchored on the rarest word in the quote rather than scanned exhaustively: a full slide would be
    O(len(hay)) SequenceMatcher calls per quote and this runs over tens of thousands of quotes. The
    anchor makes it O(occurrences of that word), which is a handful in practice.
    """
    if not needle or not hay:
        return 0.0
    n = len(needle)
    words = sorted(set(re.findall(r"[a-z]{5,}", needle)), key=lambda w: hay.count(w))
    anchors: list[int] = []
    for w in words[:3]:                      # the three rarest long words in the quote
        start = 0
        while len(anchors) < 60:
            i = hay.find(w, start)
            if i < 0:
                break
            anchors.append(i)
            start = i + 1
    if not anchors:
        anchors = [0]
    best = 0.0
    for a in anchors:
        # The anchor word may sit anywhere in the quote, so try windows that place it at several
        # offsets. Three offsets was too coarse and misaligned windows scored ~0.85 on faithful quotes.
        for frac in (0.0, 0.15, 0.3, 0.5, 0.7, 0.9):
            lo = max(0, a - int(n * frac))
            seg = hay[lo:lo + n + 60]
            if not seg:
                continue
            r = difflib.SequenceMatcher(None, needle, seg, autojunk=False).ratio()
            if r > best:
                best = r
                if best >= 0.99:
                    return best
    return best


# The model frequently abridges a long quote with an ellipsis, joining two non-contiguous spans of the
# paper. Such a quote is faithful but is not a contiguous substring, so it must be verified fragment by
# fragment or it is scored as fabricated. This was the single largest source of false "unmatched".
_ELLIPSIS = re.compile(r"\s*(?:\.\s?\.\s?\.|…)\s*")


def grounded(quote_n: str, hay: str, threshold: float) -> tuple[str, float]:
    """Classify a normalised quote against the normalised source: exact / fuzzy / unmatched."""
    frags = [f for f in _ELLIPSIS.split(quote_n) if len(f) >= 12]
    if not frags:                                   # nothing substantial left to check
        return "trivial", 1.0
    verdicts, ratios = [], []
    for f in frags:
        if f in hay:
            verdicts.append("exact")
            ratios.append(1.0)
        else:
            r = best_window_ratio(f, hay)
            ratios.append(r)
            verdicts.append("fuzzy" if r >= threshold else "unmatched")
    worst = min(ratios)
    if "unmatched" in verdicts:
        return "unmatched", worst
    return ("exact" if all(v == "exact" for v in verdicts) else "fuzzy"), worst


def iter_quotes(doc: dict):
    """Yield (kind, key, score, quote) for every quote-bearing field in an extraction record.

    The 37 panel items are nested under doc["items"], each carrying an `evidence_quote` for the score and
    an `adjusted_evidence` for the adjustment claim. Both are audited: the manuscript's promise covers
    "every item score AND every claimed adjustment".
    """
    for k, v in (doc.get("items") or {}).items():
        if not isinstance(v, dict):
            continue
        q = str(v.get("evidence_quote") or "").strip()
        if q:
            yield "item", k, v.get("score"), q, str(v.get("location") or "")
        aq = str(v.get("adjusted_evidence") or "").strip()
        if aq and v.get("adjusted"):
            yield "adjusted", k, v.get("score"), aq, str(v.get("location") or "")
    for k, v in doc.items():
        if k.endswith("_evidence") and isinstance(v, str) and v.strip():
            yield "field", k[:-9], None, v.strip(), ""          # study-level *_evidence fields
    ana = doc.get("analysis")
    if isinstance(ana, dict):
        for k, v in ana.items():
            if k.endswith("_evidence") and isinstance(v, str) and v.strip():
                yield "analysis", k[:-9], None, v.strip(), ""
    eff = doc.get("exposure_effect")
    if isinstance(eff, dict):
        for k, v in eff.items():
            if k.endswith("_evidence") and isinstance(v, str) and v.strip():
                yield "effect", k[:-9], None, v.strip(), ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="check only the first N papers (0 = all)")
    ap.add_argument("--threshold", type=float, default=0.85, help="fuzzy similarity to count as grounded")
    ap.add_argument("--cohort", default=str(ROOT / "data" / "analysis_frame.csv"),
                    help="restrict to the pmids in this frame (the analyzable cohort)")
    args = ap.parse_args()

    keep: set[str] = set()
    with open(args.cohort, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            keep.add(str(row["pmid"]).strip())

    files = sorted(p for p in EXTRACT_DIR.glob("*.json") if p.stem in keep)
    if args.sample:
        files = files[: args.sample]

    rows, n_missing_text, n_truncated = [], 0, 0
    for i, path in enumerate(files, 1):
        pmid = path.stem
        try:
            full = paper_text(pmid)
        except Exception:
            n_missing_text += 1
            continue
        if len(full) > MAX_CHARS:
            n_truncated += 1
        seen = norm(full[:MAX_CHARS])          # exactly what the model was shown
        try:
            doc = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for kind, key, score, quote, loc in iter_quotes(doc):
            q = norm(quote)
            if len(q) < 12:                     # too short to be evidence either way
                verdict, ratio = "trivial", 1.0
            else:
                verdict, ratio = grounded(q, seen, args.threshold)
            # A quote lifted from a table cannot be verified by substring search: PDF extraction
            # reflows columns, so a faithful table quote is not contiguous in the extracted text.
            # Stratifying on the model's own `location` separates "cannot verify" from "is not there".
            src = "table" if re.search(r"table|tab\.", loc, re.I) else ("text" if loc else "unspecified")
            rows.append({"pmid": pmid, "kind": kind, "key": key, "score": score, "src": src,
                         "verdict": verdict, "ratio": round(ratio, 3), "chars": len(q),
                         "location": loc[:60], "quote": quote[:300].replace("\n", " ")})
        if i % 100 == 0:
            print(f"  {i}/{len(files)} papers…", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    by = lambda v: sum(r["verdict"] == v for r in rows)  # noqa: E731
    n_ok = by("exact") + by("fuzzy") + by("trivial")
    print(f"\n  papers checked        : {len(files) - n_missing_text}  "
          f"(no text for {n_missing_text}; {n_truncated} exceeded MAX_CHARS and were truncated)")
    print(f"  quotes checked        : {n:,}")
    print(f"    exact               : {by('exact'):,} ({100*by('exact')/n:.1f}%)")
    print(f"    fuzzy >= {args.threshold}       : {by('fuzzy'):,} ({100*by('fuzzy')/n:.1f}%)")
    print(f"    too short to judge  : {by('trivial'):,}")
    print(f"    UNMATCHED           : {by('unmatched'):,} ({100*by('unmatched')/n:.1f}%)")
    print(f"  grounded overall      : {n_ok:,}/{n:,} ({100*n_ok/n:.2f}%)")

    scored = [r for r in rows if r["kind"] == "item" and r["score"] in (1, 2)]
    if scored:
        bad = sum(r["verdict"] == "unmatched" for r in scored)
        print(f"\n  non-zero ITEM scores  : {len(scored):,}  |  unmatched quote: {bad:,} "
              f"({100*bad/len(scored):.2f}%)  <- these would drop to 0 under enforcement")
    print(f"\n  per-quote detail -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
