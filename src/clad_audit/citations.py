"""Fetch citation metrics for the corpus from NIH iCite (PMID-keyed, free, no auth).

iCite returns, per PMID: citation_count (raw), relative_citation_ratio (RCR, field- and
time-normalized — the honest impact metric), nih_percentile, year, expected/cited-by fields.
We keep citation_count + RCR + nih_percentile + citations_per_year.

    uv run python -m clad_audit.citations        # -> data/citations.csv
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from .config import DATA_DIR

ICITE = "https://icite.od.nih.gov/api/pubs"
OUT = DATA_DIR / "citations.csv"
THIS_YEAR = 2026


def fetch(pmids: list[str]) -> pd.DataFrame:
    rows = []
    for i in range(0, len(pmids), 200):                      # iCite accepts up to 1000/req; 200 is polite
        batch = pmids[i : i + 200]
        r = requests.get(ICITE, params={"pmids": ",".join(batch), "format": "json"}, timeout=60)
        r.raise_for_status()
        for d in r.json().get("data", []):
            yr = d.get("year")
            cc = d.get("citation_count")
            rows.append({
                "pmid": str(d.get("pmid")),
                "cite_count": cc,
                "rcr": d.get("relative_citation_ratio"),      # None for very recent papers (<~2y)
                "nih_pctl": d.get("nih_percentile"),
                "cite_year": yr,
                "cites_per_year": round(cc / max(1, THIS_YEAR - yr), 2) if cc is not None and yr else None,
            })
        print(f"  {min(i + 200, len(pmids))}/{len(pmids)}", end="\r", flush=True)
        time.sleep(0.3)
    return pd.DataFrame(rows)


def main() -> None:
    src = DATA_DIR / "analysis_frame.csv"
    pmids = pd.read_csv(src, dtype={"pmid": str})["pmid"].astype(str).tolist()
    df = fetch(pmids)
    df.to_csv(OUT, index=False)
    print(f"\nwrote {len(df)}/{len(pmids)} citation records → {OUT}")
    print(f"  cite_count: median {df.cite_count.median():.0f}, max {df.cite_count.max():.0f}, "
          f"missing {df.cite_count.isna().sum()}")
    print(f"  RCR available for {df.rcr.notna().sum()} (None for <~2y-old papers)")


if __name__ == "__main__":
    main()
