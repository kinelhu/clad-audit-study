"""Stage 4d — Crossref-TDM-link + Springer-OA recovery for OA papers still missing full text.

Two routes the earlier passes didn't use:
  1. Crossref TDM links — publishers deposit a text-mining-intended full-text URL in Crossref metadata
     that often bypasses the browser bot-wall. Free, cross-publisher.
  2. Springer Open Access JATS API — uses SPRINGER_OPEN_ACCESS_API_KEY (previously unused) to pull
     JATS XML for Springer-hosted OA articles directly.

Resumable; skips papers that already have .pdf/.xml. Logs to data/fetch_tdm_log.csv.

    uv run python -m clad_audit.fetch_tdm
"""

from __future__ import annotations

import csv
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import DATA_DIR, PROJECT_ROOT
from .fetch import FULLTEXT_DIR, _HEADERS, _outcome

LOG = DATA_DIR / "fetch_tdm_log.csv"
ROUTED_CSV = DATA_DIR / "corpus_routed.csv"
CROSSREF = "https://api.crossref.org/works/"
SPRINGER_OA = "https://api.springernature.com/openaccess/jats"


def _save_xml(content: bytes, dest) -> bool:
    if b"<article" in content[:3000] or b"<!DOCTYPE article" in content[:3000]:
        dest.write_bytes(content)
        return True
    return False


def _crossref_links(sess: requests.Session, doi: str, ua: str) -> list[tuple[str, str]]:
    """Return [(url, content_type)] from Crossref, text-mining links first."""
    try:
        r = sess.get(f"{CROSSREF}{doi}", headers={"User-Agent": ua}, timeout=30)
        if r.status_code != 200:
            return []
        links = r.json().get("message", {}).get("link", []) or []
    except Exception:  # noqa: BLE001
        return []
    tm = [(l["URL"], l.get("content-type", "")) for l in links
          if l.get("intended-application") == "text-mining" and l.get("URL")]
    other = [(l["URL"], l.get("content-type", "")) for l in links
             if l.get("intended-application") != "text-mining" and l.get("URL")]
    return tm + other  # prefer text-mining-intended


def _try_springer_oa(sess: requests.Session, doi: str, key: str, dest) -> bool:
    try:
        r = sess.get(SPRINGER_OA, params={"q": f"doi:{doi}", "api_key": key}, timeout=45)
        if r.status_code == 200 and _save_xml(r.content, dest):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    ua = f"clad-audit/0.1 (mailto:{os.environ.get('UNPAYWALL_EMAIL', 'research@example.org')})"
    springer_key = os.environ.get("SPRINGER_OPEN_ACCESS_API_KEY", "").strip()

    df = pd.read_csv(ROUTED_CSV, dtype={"pmid": str, "doi": str, "publisher": str})
    have = {p.stem for p in FULLTEXT_DIR.glob("*.pdf")} | {p.stem for p in FULLTEXT_DIR.glob("*.xml")}
    todo = df[(df["tier"] == "OA") & (~df["pmid"].isin(have)) & df["doi"].notna()]
    print(f"OA still missing full text: {len(todo)}")

    sess = requests.Session()
    counts: dict[str, int] = {}
    log_exists = LOG.exists()
    with LOG.open("a", newline="") as fh:
        w = csv.writer(fh)
        if not log_exists:
            w.writerow(["pmid", "doi", "outcome"])
        for i, row in enumerate(todo.itertuples(), 1):
            outcome = "failed"
            pdf_dest = FULLTEXT_DIR / f"{row.pmid}.pdf"
            xml_dest = FULLTEXT_DIR / f"{row.pmid}.xml"
            # 1. Crossref TDM links
            for url, ctype in _crossref_links(sess, row.doi, ua):
                if "xml" in ctype:
                    try:
                        rr = sess.get(url, headers=_HEADERS, timeout=60)
                        if rr.status_code == 200 and _save_xml(rr.content, xml_dest):
                            outcome = "crossref_xml"
                            break
                    except Exception:  # noqa: BLE001
                        continue
                else:
                    oc, _ = _outcome(sess, url, pdf_dest)
                    if oc == "saved_pdf":
                        outcome = "crossref_pdf"
                        break
            # 2. Springer OA JATS (if still missing and looks like Springer)
            if outcome == "failed" and springer_key and "springer" in str(row.publisher).lower():
                if _try_springer_oa(sess, row.doi, springer_key, xml_dest):
                    outcome = "springer_oa_xml"
            counts[outcome] = counts.get(outcome, 0) + 1
            w.writerow([row.pmid, row.doi, outcome])
            fh.flush()
            if i % 50 == 0:
                got = sum(v for k, v in counts.items() if k != "failed")
                print(f"  {i}/{len(todo)}  (+{got})", end="\r", flush=True)
            time.sleep(0.15)

    print("\n\n=== TDM recovery outcomes ===")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<16} {v}")
    nx = len(list(FULLTEXT_DIR.glob("*.xml")))
    np_ = len(list(FULLTEXT_DIR.glob("*.pdf")))
    print(f"\nfull text on disk now: {nx} XML + {np_} PDF = {nx + np_}")


if __name__ == "__main__":
    main()
