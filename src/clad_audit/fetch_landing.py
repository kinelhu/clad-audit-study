"""Stage 4b — landing-page fetch (recovers the `not_pdf(text/html)` and some 403 cases).

`fetch.py` requests Unpaywall's best-OA URL and keeps the body only if it starts with %PDF.
For ~229 records that URL resolves to a LANDING PAGE, which is discarded. This module follows
the landing page and looks for the publisher's own advertised PDF link -- primarily the
`citation_pdf_url` <meta> tag that publishers emit for Google Scholar indexing. That is
published metadata, not circumvention.

Differences from fetch.py, all deliberate (see docs/retrieval-status.md):
  * per-HOST throttle + exponential backoff honouring Retry-After -- fetch.py's flat 0.2 s
    global sleep earned 9x http_429 and probably provoked some 403s
  * complete, consistent headers. fetch.py claims Chrome but sends a python-requests TLS
    fingerprint with no Accept-Language/Referer -- the mismatch is what bot scoring keys on.
    --ua honest (default) identifies the crawler with a contact address; --ua browser sends a
    coherent browser header set. Both are logged so the yield difference is measurable.
  * Referer set to the landing page when fetching the PDF (several publishers require it)

Resumable: any pmid already in data/fulltext/ is skipped. Never overwrites. Appends to
data/fetch_landing_log.csv. Does not touch fetch.py or its log.

    uv run python -m clad_audit.fetch_landing --limit 60           # pilot
    uv run python -m clad_audit.fetch_landing --ua browser --limit 60
    uv run python -m clad_audit.fetch_landing                      # full worklist
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from lxml import html as lxml_html

from .config import DATA_DIR

FULLTEXT_DIR = DATA_DIR / "fulltext"
LOG = DATA_DIR / "fetch_landing_log.csv"
WORKLIST = DATA_DIR / "retrieval_worklist.csv"

# From .env, like every other module that needs a polite-pool address (route.py, fetch_tdm.py). It was
# a personal Gmail hardcoded here, which shipped to the public repository in the source rather than in
# a data column, where the export's leak check was not looking.
CONTACT = os.environ.get("UNPAYWALL_EMAIL", "research@example.org")
_UA_HONEST = f"clad-reporting-audit/1.0 (academic systematic review; mailto:{CONTACT})"
_UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _headers(ua_mode: str, accept: str, referer: str | None = None) -> dict[str, str]:
    """Coherent header set. The point is that UA and the rest agree with each other."""
    h = {
        "User-Agent": _UA_HONEST if ua_mode == "honest" else _UA_BROWSER,
        "Accept": accept,
        "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if ua_mode == "browser":
        h.update({
            "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })
    if referer:
        h["Referer"] = referer
    return h


class HostThrottle:
    """Minimum interval between requests to the same host, with jitter and 429/503 backoff."""

    def __init__(self, min_interval: float = 3.0) -> None:
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._penalty: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        gap = self.min_interval + self._penalty.get(host, 0.0) + random.uniform(0, 0.8)
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last[host] = time.monotonic()

    def penalise(self, url: str, retry_after: str | None) -> None:
        """Grow this host's floor after a 429/503; respect Retry-After when sane."""
        host = urlparse(url).netloc
        cur = self._penalty.get(host, 0.0)
        bump = min(float(retry_after), 60.0) if (retry_after or "").isdigit() else max(2.0, cur * 2 or 2.0)
        self._penalty[host] = min(cur + bump, 60.0)

    def relax(self, url: str) -> None:
        host = urlparse(url).netloc
        if host in self._penalty:
            self._penalty[host] = max(0.0, self._penalty[host] * 0.5)


def _is_pdf(body: bytes) -> bool:
    return body.lstrip()[:5].startswith(b"%PDF")


def _pdf_links(page: bytes, base_url: str) -> list[str]:
    """Candidate PDF URLs from a landing page, best first.

    citation_pdf_url is the publisher's own machine-readable pointer (emitted for Google
    Scholar). The <a> fallbacks are deliberately narrow to avoid grabbing supplements.
    """
    # (rank, url) — rank 0 = publisher's own citation_pdf_url, 1 = <a> corroborated by link
    # text, 2 = <a> matched on URL shape alone. Sorted stably so the safest bet is tried first.
    out: list[tuple[int, str]] = []
    try:
        doc = lxml_html.fromstring(page)
    except Exception:  # noqa: BLE001 — malformed HTML, fall through to regex
        doc = None

    if doc is not None:
        for meta in doc.xpath('//meta[@name="citation_pdf_url" or @name="wkhealth_pdf_url"]'):
            if (c := meta.get("content")):
                out.append((0, urljoin(base_url, c.strip())))
        for a in doc.xpath('//a[@href]'):
            href = a.get("href", "").strip()
            txt = " ".join(a.itertext()).lower().strip()
            if not href or href.startswith("#"):
                continue
            low = href.lower()
            # match on the PATH, not the whole href: DSpace/EPrints repositories serve
            # /bitstream/handle/.../file.pdf?sequence=1 — a query string defeats endswith()
            path = urlparse(low).path
            looks_pdf = (path.endswith(".pdf") or "/pdf" in path or "type=printable" in low
                         or "/bitstream/" in path or "/download" in path or "/fulltext" in path)
            # link text is corroborating, not required: repository download buttons say
            # "Download" or show a filename, never "PDF"
            says_pdf = "pdf" in txt or "full text" in txt or "download" in txt or "open" in txt
            is_suppl = "suppl" in low or "supplement" in txt or "appendix" in txt
            if looks_pdf and not is_suppl:
                out.append((1 if says_pdf else 2, urljoin(base_url, href)))

    # regex fallback for pages lxml can't parse
    if not out:
        for m in re.finditer(rb'citation_pdf_url"?\s+content="([^"]+)"', page):
            out.append((0, urljoin(base_url, m.group(1).decode(errors="replace"))))

    seen, uniq = set(), []
    for _rank, u in sorted(out, key=lambda t: t[0]):
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:4]


def _get(sess, url, throttle, ua_mode, accept, referer=None, timeout=60):
    throttle.wait(url)
    try:
        r = sess.get(url, headers=_headers(ua_mode, accept, referer), timeout=timeout,
                     allow_redirects=True)
    except Exception as e:  # noqa: BLE001
        return None, f"exception:{type(e).__name__}"
    if r.status_code in (429, 503):
        throttle.penalise(url, r.headers.get("Retry-After"))
        return r, f"http_{r.status_code}"
    if r.status_code == 200:
        throttle.relax(url)
    return r, f"http_{r.status_code}"


def fetch_one(sess, pmid, url, throttle, ua_mode) -> tuple[str, int, str]:
    """Return (outcome, bytes, final_pdf_url). Writes the PDF only on success."""
    dest = FULLTEXT_DIR / f"{pmid}.pdf"
    r, status = _get(sess, url, throttle, ua_mode, "application/pdf,text/html;q=0.9,*/*;q=0.8")
    if r is None:
        return status, 0, ""
    if r.status_code != 200:
        return f"landing_{status}", 0, ""

    if _is_pdf(r.content):                      # the URL was a real PDF after all
        dest.write_bytes(r.content)
        return "saved_pdf_direct", len(r.content), r.url

    ctype = r.headers.get("Content-Type", "").split(";")[0]
    if "html" not in ctype:
        return f"not_pdf({ctype})", len(r.content), r.url

    cands = _pdf_links(r.content, r.url)
    if not cands:
        return "no_pdf_link", len(r.content), r.url

    for cand in cands:
        r2, status2 = _get(sess, cand, throttle, ua_mode, "application/pdf,*/*", referer=r.url)
        if r2 is None or r2.status_code != 200:
            continue
        if _is_pdf(r2.content):
            dest.write_bytes(r2.content)
            return "saved_pdf_landing", len(r2.content), cand
    return f"pdf_link_failed({len(cands)})", 0, cands[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ua", choices=["honest", "browser"], default="honest")
    ap.add_argument("--min-interval", type=float, default=3.0, help="seconds between hits per host")
    ap.add_argument("--tiers", default="OA", help="comma list of worklist tiers, or 'all'")
    ap.add_argument("--shuffle", action="store_true",
                    help="interleave hosts so one publisher isn't hit in a long run")
    args = ap.parse_args()

    wl = pd.read_csv(WORKLIST, dtype={"pmid": str, "doi": str})
    if args.tiers != "all":
        wl = wl[wl["tier"].isin([t.strip() for t in args.tiers.split(",")])]
    # a landing page needs a URL: prefer Unpaywall's, else resolve via doi.org
    wl = wl.assign(start_url=wl["oa_pdf_url"].fillna("").where(
        wl["oa_pdf_url"].notna() & (wl["oa_pdf_url"] != ""),
        "https://doi.org/" + wl["doi"].fillna("")))
    wl = wl[wl["start_url"].str.startswith("http")]

    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in FULLTEXT_DIR.iterdir() if p.is_file()}
    todo = wl[~wl["pmid"].isin(done)].copy()

    if args.shuffle:  # spread load across hosts rather than hammering one
        todo["_host"] = todo["start_url"].map(lambda u: urlparse(u).netloc)
        todo["_k"] = todo.groupby("_host").cumcount()
        todo = todo.sort_values(["_k", "_host"]).drop(columns=["_k", "_host"])
    if args.limit:
        todo = todo.head(args.limit)

    print(f"worklist: {len(wl)} | on disk: {len(done)} | attempting: {len(todo)} | ua={args.ua}")
    throttle = HostThrottle(args.min_interval)
    sess = requests.Session()
    log_exists = LOG.exists()
    counts: dict[str, int] = {}

    with LOG.open("a", newline="") as fh:
        w = csv.writer(fh)
        if not log_exists:
            w.writerow(["pmid", "doi", "tier", "ua", "start_url", "outcome", "bytes", "pdf_url"])
        for i, row in enumerate(todo.itertuples(), 1):
            outcome, nbytes, pdf_url = fetch_one(sess, row.pmid, row.start_url, throttle, args.ua)
            key = outcome.split("(")[0].split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            w.writerow([row.pmid, row.doi, row.tier, args.ua, row.start_url, outcome, nbytes, pdf_url])
            fh.flush()
            got = sum(v for k, v in counts.items() if k.startswith("saved_pdf"))
            print(f"  {i}/{len(todo)}  {row.pmid:>9}  {outcome[:38]:<38} saved={got}", flush=True)

    print("\n=== outcomes this run ===")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<26} {v}")
    got = sum(v for k, v in counts.items() if k.startswith("saved_pdf"))
    print(f"\nrecovered {got}/{len(todo)} ({got / max(len(todo), 1):.0%}) | log: {LOG}")


if __name__ == "__main__":
    main()
