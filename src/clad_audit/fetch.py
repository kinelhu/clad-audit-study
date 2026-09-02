"""Stage 4 — fetch (OA tier).

Download full-text PDFs for the OA tier from Unpaywall's best-OA PDF URL. Solid OA
(gold/hybrid/green) first, bronze best-effort (publisher-hosted, may Cloudflare-block). This is the
pluggable per-DOI queue — Elsevier / Wiley / ISTEX slot in as extra tiers later without re-running
discovery/routing.

Resumable: a saved PDF is skipped. Every attempt is logged to data/fetch_log.csv.

    uv run python -m clad_audit.fetch                 # all OA, solid first
    uv run python -m clad_audit.fetch --limit 15      # pilot batch
    uv run python -m clad_audit.fetch --statuses gold,hybrid,green

ISTEX archive fallback for pre-2019 paywalled content is a later addition (separate tier).
"""

from __future__ import annotations

import argparse
import csv
import time

import pandas as pd
import requests

from .config import DATA_DIR

FULLTEXT_DIR = DATA_DIR / "fulltext"
FETCH_LOG = DATA_DIR / "fetch_log.csv"
ROUTED_CSV = DATA_DIR / "corpus_routed.csv"

_SOLID = ["gold", "hybrid", "green"]
_HEADERS = {
    # browser-like UA — some OA hosts 403 the default python UA
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}


def _outcome(sess: requests.Session, url: str, dest) -> tuple[str, int]:
    """Download url to dest if it is a PDF. Return (outcome, bytes)."""
    try:
        r = sess.get(url, headers=_HEADERS, timeout=60, allow_redirects=True)
    except Exception as e:  # noqa: BLE001 — any transport error (chunk, TLS, timeout, ...)
        return f"exception:{type(e).__name__}", 0
    if r.status_code != 200:
        return f"http_{r.status_code}", 0
    body = r.content
    if not body[:5].startswith(b"%PDF"):
        ctype = r.headers.get("Content-Type", "").split(";")[0]
        return f"not_pdf({ctype})", len(body)
    dest.write_bytes(body)
    return "saved_pdf", len(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max papers to fetch this run")
    ap.add_argument("--statuses", default="gold,hybrid,green,bronze",
                    help="comma list of oa_status to include (default all)")
    args = ap.parse_args()
    want = [s.strip() for s in args.statuses.split(",") if s.strip()]

    df = pd.read_csv(ROUTED_CSV, dtype={"doi": str, "pmid": str})
    oa = df[(df["tier"] == "OA") & df["oa_pdf_url"].notna() & (df["oa_pdf_url"] != "")].copy()
    oa = oa[oa["oa_status"].isin(want)]
    # solid first, then bronze; stable within group
    oa["_rank"] = oa["oa_status"].map({s: i for i, s in enumerate(_SOLID)}).fillna(9)
    oa = oa.sort_values(["_rank", "pmid"]).reset_index(drop=True)

    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    log_exists = FETCH_LOG.exists()
    sess = requests.Session()

    done = {p.stem for p in FULLTEXT_DIR.glob("*.pdf")}
    todo = oa[~oa["pmid"].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"OA candidates: {len(oa)} | already saved: {len(done)} | fetching: {len(todo)}")

    counts: dict[str, int] = {}
    with FETCH_LOG.open("a", newline="") as fh:
        w = csv.writer(fh)
        if not log_exists:
            w.writerow(["pmid", "doi", "oa_status", "url", "outcome", "bytes"])
        for i, row in enumerate(todo.itertuples(), 1):
            dest = FULLTEXT_DIR / f"{row.pmid}.pdf"
            outcome, nbytes = _outcome(sess, row.oa_pdf_url, dest)
            key = outcome.split("(")[0].split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            w.writerow([row.pmid, row.doi, row.oa_status, row.oa_pdf_url, outcome, nbytes])
            fh.flush()
            print(f"  {i}/{len(todo)}  {row.pmid}  {outcome}", end="\r", flush=True)
            time.sleep(0.2)

    print("\n\n=== fetch outcomes this run ===")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<22} {v}")
    saved = len(list(FULLTEXT_DIR.glob("*.pdf")))
    print(f"\ntotal PDFs on disk: {saved}  (in {FULLTEXT_DIR})")
    print(f"log: {FETCH_LOG}")


if __name__ == "__main__":
    main()
