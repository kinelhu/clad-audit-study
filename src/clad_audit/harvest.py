"""Stage 1 — harvest.

Run the locked PubMed query and cache the full metadata as efetch XML batches.
Uses the E-utilities history server (WebEnv/query_key) so we page the whole result set from a
single search. Resumable: existing non-empty batch files are skipped.

    uv run python -m clad_audit.harvest
"""

from __future__ import annotations

import os
import sys
import time

import requests
from dotenv import load_dotenv

from .config import (
    EFETCH_BATCH,
    EUTILS,
    PROJECT_ROOT,
    QUERY,
    RAW_DIR,
    SLEEP_NO_KEY,
    SLEEP_WITH_KEY,
)


def _esearch(key: str) -> tuple[int, str, str]:
    """Post the query with history; return (count, webenv, query_key)."""
    params = {"db": "pubmed", "term": QUERY, "usehistory": "y", "retmax": 0, "retmode": "json"}
    if key:
        params["api_key"] = key
    r = requests.post(EUTILS + "esearch.fcgi", data=params, timeout=60)
    r.raise_for_status()
    res = r.json()["esearchresult"]
    if "ERROR" in res:
        sys.exit(f"esearch error: {res['ERROR']}")
    return int(res["count"]), res["webenv"], res["querykey"]


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("NCBI_API_KEY", "").strip()
    sleep = SLEEP_WITH_KEY if key else SLEEP_NO_KEY
    print(f"NCBI key: {'present' if key else 'MISSING (rate-limited to <3/s)'}")

    count, webenv, qk = _esearch(key)
    print(f"query matched {count} records; fetching in batches of {EFETCH_BATCH}")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "_count.txt").write_text(str(count))

    fetched = 0
    for start in range(0, count, EFETCH_BATCH):
        out = RAW_DIR / f"efetch_{start:05d}.xml"
        if out.exists() and out.stat().st_size > 0:
            continue
        params = {
            "db": "pubmed",
            "query_key": qk,
            "WebEnv": webenv,
            "retstart": start,
            "retmax": EFETCH_BATCH,
            "retmode": "xml",
        }
        if key:
            params["api_key"] = key
        for attempt in range(4):
            try:
                rr = requests.post(EUTILS + "efetch.fcgi", data=params, timeout=180)
                rr.raise_for_status()
                if not rr.content.strip().endswith(b"</PubmedArticleSet>"):
                    raise ValueError("truncated batch")
                out.write_bytes(rr.content)
                break
            except Exception as e:  # noqa: BLE001 — retry any transient failure
                wait = 2 ** attempt
                print(f"  batch {start}: {e} (retry in {wait}s)", file=sys.stderr)
                time.sleep(wait)
        else:
            sys.exit(f"batch {start} failed after retries")
        fetched += 1
        print(f"  {start + EFETCH_BATCH:>5}/{count}", end="\r", flush=True)
        time.sleep(sleep)

    print(f"\ndone: {fetched} new batches, {len(list(RAW_DIR.glob('efetch_*.xml')))} total in {RAW_DIR}")


if __name__ == "__main__":
    main()
