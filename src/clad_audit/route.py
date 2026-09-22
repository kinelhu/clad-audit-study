"""Stage 3 — route.

For each DOI, ask Unpaywall for OA status + best OA PDF location + publisher, then assign a
full-text acquisition tier. Answers the decision question: what fraction is free (OA), and how
many studies sit behind each paywalled publisher (Elsevier / Wiley / Springer / Wolters Kluwer / …).

Resumable: responses cached to data/interim/unpaywall.jsonl (one line per DOI); cached DOIs skipped.
Keyless — uses UNPAYWALL_EMAIL from .env (Unpaywall's polite-pool requirement).

    uv run python -m clad_audit.route

Writes data/corpus_routed.csv (corpus + tier/oa_status/oa_pdf_url/publisher). ISTEX is a cross-cutting
archive fallback tried in the fetch stage, not a tier here.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import CORPUS_CSV, DATA_DIR, INTERIM_DIR, PROJECT_ROOT

UNPAYWALL = "https://api.unpaywall.org/v2/"
CACHE = INTERIM_DIR / "unpaywall.jsonl"
ROUTED_CSV = DATA_DIR / "corpus_routed.csv"


def _load_cache() -> dict[str, dict]:
    seen: dict[str, dict] = {}
    if CACHE.exists():
        for line in CACHE.open():
            line = line.strip()
            if line:
                rec = json.loads(line)
                seen[rec["doi"]] = rec
    return seen


def _fetch(dois: list[str], email: str) -> dict[str, dict]:
    seen = _load_cache()
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    todo = [d for d in dois if d not in seen]
    print(f"{len(seen)} cached, {len(todo)} to fetch")
    with CACHE.open("a") as f:
        for i, doi in enumerate(todo, 1):
            rec: dict = {"doi": doi}
            try:
                # DOI goes raw in the path (slashes preserved); email as query param.
                r = requests.get(f"{UNPAYWALL}{doi}", params={"email": email}, timeout=30)
                if r.status_code == 200:
                    rec["resp"] = r.json()
                elif r.status_code == 404:
                    rec["resp"] = None
                    rec["note"] = "not in unpaywall"
                else:
                    rec["error"] = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                rec["error"] = str(e)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            seen[doi] = rec
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", end="\r", flush=True)
            time.sleep(0.1)  # ~10/s, polite
    print()
    return seen


def _tier(resp: dict | None) -> tuple[str, str, str, str]:
    """Return (tier, oa_status, oa_pdf_url, publisher)."""
    if resp is None:
        return "unresolved", "", "", ""
    oa_status = resp.get("oa_status") or ""
    publisher = resp.get("publisher") or ""
    best = resp.get("best_oa_location") or {}
    pdf = best.get("url_for_pdf") or best.get("url") or ""
    if resp.get("is_oa") and pdf:
        return "OA", oa_status, pdf, publisher
    p = publisher.lower()
    if "elsevier" in p:
        tier = "Elsevier"
    elif "wiley" in p:
        tier = "Wiley"
    elif "springer" in p or "nature" in p:
        tier = "Springer"
    elif any(k in p for k in ("wolters", "ovid", "lippincott")):
        tier = "WoltersKluwer"
    elif "thoracic society" in p:
        tier = "ATS"
    elif p:
        tier = "Other-paywall"
    else:
        tier = "unresolved"
    return tier, oa_status, pdf, publisher


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    email = os.environ.get("UNPAYWALL_EMAIL", "").strip()
    if not email:
        sys.exit("UNPAYWALL_EMAIL missing from .env (Unpaywall requires it).")

    df = pd.read_csv(CORPUS_CSV, dtype={"doi": str})
    dois = [d for d in df["doi"].dropna().unique().tolist() if d]
    seen = _fetch(dois, email)

    def route(doi):
        if not isinstance(doi, str) or not doi:
            return ("no-doi", "", "", "")
        rec = seen.get(doi, {})
        return _tier(rec.get("resp"))

    routed = df["doi"].map(route)
    df["tier"] = [r[0] for r in routed]
    df["oa_status"] = [r[1] for r in routed]
    df["oa_pdf_url"] = [r[2] for r in routed]
    df["publisher"] = [r[3] for r in routed]
    df.to_csv(ROUTED_CSV, index=False)

    # --- decision report ---
    n = len(df)
    oa = (df["tier"] == "OA").sum()
    print(f"\nrouted {n} studies")
    print(f"\n=== full-text tier (the acquisition plan) ===")
    for t, c in df["tier"].value_counts().items():
        print(f"  {t:<16} {c:>4}  ({c / n:.0%})")
    print(f"\nOA (free now): {oa} ({oa / n:.0%})")
    live = df["tier"].isin(["OA"]).sum()
    print("  OA status breakdown:")
    for s, c in df.loc[df["tier"] == "OA", "oa_status"].value_counts().items():
        print(f"    {s:<10} {c}")
    print(f"\n=== OA fraction by era (does recent content skew OA?) ===")
    print((df.assign(is_oa=df["tier"] == "OA").groupby("era")["is_oa"].mean().round(2)).to_string())
    print(f"\n=== gated counts (what each token/route would unlock) ===")
    for t in ("Elsevier", "Wiley", "Springer", "WoltersKluwer", "ATS", "Other-paywall", "unresolved", "no-doi"):
        c = (df["tier"] == t).sum()
        if c:
            print(f"  {t:<16} {c:>4}")
    print(f"\nwrote {ROUTED_CSV}")


if __name__ == "__main__":
    main()
