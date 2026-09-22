"""Stage 4c — retry fetch for OA papers still missing full text.

Unpaywall's best_oa_location often points at an HTML landing page or a bot-walled PDF. This recovers
more by (a) trying ALL oa_locations (not just best), and (b) parsing the landing page's
<meta name="citation_pdf_url"> to find the real PDF. Targets OA-tier papers with no .pdf/.xml yet.

    uv run python -m clad_audit.fetch_retry

Resumable (skips papers that now have full text). Logs to data/fetch_retry_log.csv.
"""

from __future__ import annotations

import csv
import json
import re
import time

import pandas as pd
import requests

from .config import DATA_DIR
from .fetch import FULLTEXT_DIR, _HEADERS, _outcome

CACHE = DATA_DIR / "interim" / "unpaywall.jsonl"
ROUTED = DATA_DIR / "corpus_routed.csv"
LOG = DATA_DIR / "fetch_retry_log.csv"
_CIT_META = re.compile(r"<meta[^>]+citation_pdf_url[^>]*>", re.I)
_CONTENT = re.compile(r'content=["\']([^"\']+)["\']', re.I)


def _cache_by_doi() -> dict[str, dict]:
    d: dict[str, dict] = {}
    if CACHE.exists():
        for line in CACHE.open():
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("resp"):
                    d[r["doi"]] = r["resp"]
    return d


def _candidate_pdf_urls(resp: dict) -> list[str]:
    urls: list[str] = []
    for loc in resp.get("oa_locations") or []:
        for u in (loc.get("url_for_pdf"), loc.get("url")):
            if u and u not in urls:
                urls.append(u)
    return urls


def _citation_pdf_url(sess: requests.Session, url: str) -> str | None:
    try:
        r = sess.get(url, headers=_HEADERS, timeout=45)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    m = _CIT_META.search(r.text)
    if m:
        c = _CONTENT.search(m.group(0))
        if c:
            return c.group(1)
    return None


def main() -> None:
    df = pd.read_csv(ROUTED, dtype={"pmid": str, "doi": str})
    have = {p.stem for p in FULLTEXT_DIR.glob("*.pdf")} | {p.stem for p in FULLTEXT_DIR.glob("*.xml")}
    cache = _cache_by_doi()
    todo = df[(df["tier"] == "OA") & (~df["pmid"].isin(have)) & df["doi"].notna()]
    print(f"OA-tier papers still missing full text: {len(todo)}")

    sess = requests.Session()
    counts: dict[str, int] = {}
    log_exists = LOG.exists()
    with LOG.open("a", newline="") as fh:
        w = csv.writer(fh)
        if not log_exists:
            w.writerow(["pmid", "doi", "outcome"])
        for i, row in enumerate(todo.itertuples(), 1):
            resp = cache.get(row.doi)
            outcome = "no_cache"
            if resp:
                dest = FULLTEXT_DIR / f"{row.pmid}.pdf"
                outcome = "failed"
                for u in _candidate_pdf_urls(resp):
                    oc, _ = _outcome(sess, u, dest)
                    if oc == "saved_pdf":
                        outcome = "saved_alt"
                        break
                    if oc.startswith("not_pdf"):
                        pu = _citation_pdf_url(sess, u)
                        if pu:
                            oc2, _ = _outcome(sess, pu, dest)
                            if oc2 == "saved_pdf":
                                outcome = "saved_citmeta"
                                break
            counts[outcome] = counts.get(outcome, 0) + 1
            w.writerow([row.pmid, row.doi, outcome])
            fh.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}  (+{counts.get('saved_alt',0)+counts.get('saved_citmeta',0)})",
                      end="\r", flush=True)
            time.sleep(0.2)

    print("\n\n=== retry outcomes ===")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<14} {v}")
    nx = len(list(FULLTEXT_DIR.glob("*.xml")))
    np_ = len(list(FULLTEXT_DIR.glob("*.pdf")))
    print(f"\nfull text on disk now: {nx} XML + {np_} PDF = {nx + np_}")


if __name__ == "__main__":
    main()
