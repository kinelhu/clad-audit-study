"""Stage 4b — Europe PMC full-text XML tier.

For every PMID, ask Europe PMC whether an open full text exists (inEPMC=Y) and pull the JATS XML.
Runs over the WHOLE corpus, not just the OA tier: many paywalled (Elsevier / Wolters Kluwer) papers
have an NIH author manuscript in PMC, so this recovers free full text beyond Unpaywall's OA set — and
JATS XML is cleaner for extraction than a scraped PDF.

Resumable: skips a PMID that already has a saved .xml or .pdf. Logs to data/fetch_epmc_log.csv.

    uv run python -m clad_audit.fetch_epmc
"""

from __future__ import annotations

import csv
import time

import pandas as pd
import requests

from .config import DATA_DIR

FULLTEXT_DIR = DATA_DIR / "fulltext"
LOG = DATA_DIR / "fetch_epmc_log.csv"
ROUTED_CSV = DATA_DIR / "corpus_routed.csv"
SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
_HEADERS = {"User-Agent": "clad-audit/0.1 (research TDM)"}


def _lookup(sess: requests.Session, pmid: str) -> tuple[str, str]:
    """Return (pmcid, in_epmc) for a PMID via Europe PMC search."""
    r = sess.get(
        SEARCH,
        params={"query": f"EXT_ID:{pmid} AND SRC:MED", "resultType": "core", "format": "json"},
        headers=_HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    results = r.json().get("resultList", {}).get("result", [])
    if not results:
        return "", "N"
    hit = results[0]
    return hit.get("pmcid", ""), hit.get("inEPMC", "N")


def _fulltext(sess: requests.Session, pmcid: str, dest) -> str:
    r = sess.get(FULLTEXT.format(pmcid=pmcid), headers=_HEADERS, timeout=60)
    if r.status_code != 200:
        return f"xml_http_{r.status_code}"
    if b"<article" not in r.content[:2000]:
        return "not_jats"
    dest.write_bytes(r.content)
    return "saved_xml"


def main() -> None:
    df = pd.read_csv(ROUTED_CSV, dtype={"pmid": str})
    have = {p.stem for p in FULLTEXT_DIR.glob("*.pdf")} | {p.stem for p in FULLTEXT_DIR.glob("*.xml")}
    todo = [p for p in df["pmid"].dropna().tolist() if p and p not in have]
    print(f"corpus {len(df)} | already have full text {len(have)} | trying Europe PMC on {len(todo)}")
    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)

    sess = requests.Session()
    counts: dict[str, int] = {}
    log_exists = LOG.exists()
    with LOG.open("a", newline="") as fh:
        w = csv.writer(fh)
        if not log_exists:
            w.writerow(["pmid", "pmcid", "in_epmc", "outcome"])
        for i, pmid in enumerate(todo, 1):
            try:
                pmcid, in_epmc = _lookup(sess, pmid)
                if in_epmc == "Y" and pmcid:
                    outcome = _fulltext(sess, pmcid, FULLTEXT_DIR / f"{pmid}.xml")
                else:
                    outcome = "no_open_fulltext"
            except Exception as e:  # noqa: BLE001
                pmcid, in_epmc, outcome = "", "", f"exception:{type(e).__name__}"
            counts[outcome.split(":")[0]] = counts.get(outcome.split(":")[0], 0) + 1
            w.writerow([pmid, pmcid, in_epmc, outcome])
            fh.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}  (+{counts.get('saved_xml', 0)} xml)", end="\r", flush=True)
            time.sleep(0.12)

    print("\n\n=== Europe PMC outcomes this run ===")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<18} {v}")
    xml = len(list(FULLTEXT_DIR.glob("*.xml")))
    pdf = len(list(FULLTEXT_DIR.glob("*.pdf")))
    print(f"\nfull text on disk: {xml} XML + {pdf} PDF = {xml + pdf}")


if __name__ == "__main__":
    main()
