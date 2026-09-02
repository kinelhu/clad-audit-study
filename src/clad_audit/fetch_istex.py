"""Stage 4e — ISTEX archive full text (uses ISTEX_ACCESS_TOKEN, previously unused).

Recovers older paywalled content ISTEX mirrors under a ~3-4y moving wall (strong on Transplantation
Proceedings / Transplant Immunology / misc older Elsevier-Wiley-Springer; NOT JHLT/AJT recent → those
need the Elsevier insttoken). Search by DOI → pick pdf (else txt) → download with the Bearer token.

Runs over ALL papers still missing full text (any tier). Resumable; logs to data/fetch_istex_log.csv.

    uv run python -m clad_audit.fetch_istex
"""

from __future__ import annotations

import csv
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import DATA_DIR, PROJECT_ROOT
from .fetch import FULLTEXT_DIR

LOG = DATA_DIR / "fetch_istex_log.csv"
ROUTED_CSV = DATA_DIR / "corpus_routed.csv"
SEARCH = "https://api.istex.fr/document/"
BASE = "https://api.istex.fr"


def _search(sess: requests.Session, doi: str, token: str) -> tuple[str, str] | None:
    """Return (ext, uri) for the best available full-text format, or None."""
    r = sess.get(
        SEARCH,
        params={"q": f'doi:"{doi}"', "size": 1, "output": "id,fulltext"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    hits = r.json().get("hits", [])
    if not hits:
        return None
    by_ext = {f.get("extension"): f.get("uri") for f in hits[0].get("fulltext", []) if f.get("uri")}
    for ext in ("pdf", "txt"):
        if ext in by_ext:
            return ext, by_ext[ext]
    return None


def _download(sess: requests.Session, uri: str, token: str, ext: str, dest) -> str:
    url = uri if uri.startswith("http") else BASE + uri  # ISTEX returns absolute URLs
    r = sess.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=90)
    if r.status_code != 200:
        return f"dl_http_{r.status_code}"
    if ext == "pdf" and not r.content[:5].startswith(b"%PDF"):
        return "not_pdf"
    dest.write_bytes(r.content)
    return "saved"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.environ.get("ISTEX_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("ISTEX_ACCESS_TOKEN missing from .env")

    df = pd.read_csv(ROUTED_CSV, dtype={"pmid": str, "doi": str})
    have = ({p.stem for p in FULLTEXT_DIR.glob("*.pdf")}
            | {p.stem for p in FULLTEXT_DIR.glob("*.xml")}
            | {p.stem for p in FULLTEXT_DIR.glob("*.txt")})
    todo = df[(~df["pmid"].isin(have)) & df["doi"].notna()]
    print(f"missing with DOI: {len(todo)} — querying ISTEX")

    sess = requests.Session()
    counts: dict[str, int] = {}
    log_exists = LOG.exists()
    with LOG.open("a", newline="") as fh:
        w = csv.writer(fh)
        if not log_exists:
            w.writerow(["pmid", "doi", "outcome"])
        for i, row in enumerate(todo.itertuples(), 1):
            outcome = "no_hit"
            try:
                found = _search(sess, row.doi, token)
                if found:
                    ext, uri = found
                    dest = FULLTEXT_DIR / f"{row.pmid}.{'pdf' if ext == 'pdf' else 'txt'}"
                    oc = _download(sess, uri, token, ext, dest)
                    outcome = f"saved_{ext}" if oc == "saved" else oc
            except Exception as e:  # noqa: BLE001
                outcome = f"exception:{type(e).__name__}"
            counts[outcome.split(":")[0]] = counts.get(outcome.split(":")[0], 0) + 1
            w.writerow([row.pmid, row.doi, outcome])
            fh.flush()
            if i % 100 == 0:
                got = sum(v for k, v in counts.items() if k.startswith("saved"))
                print(f"  {i}/{len(todo)} (+{got})", end="\r", flush=True)
            time.sleep(0.15)

    print("\n\n=== ISTEX outcomes ===")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<16} {v}")
    nx = len(list(FULLTEXT_DIR.glob("*.xml")))
    np_ = len(list(FULLTEXT_DIR.glob("*.pdf")))
    nt = len(list(FULLTEXT_DIR.glob("*.txt")))
    print(f"\nfull text on disk: {nx} XML + {np_} PDF + {nt} TXT = {nx + np_ + nt}")


if __name__ == "__main__":
    main()
