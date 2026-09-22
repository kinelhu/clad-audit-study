"""reextract_effort.py — does the extraction depend on the reasoning-effort setting, and is it repeatable?

Two questions, one sample, one batch job.

  D2 (effort sensitivity). The covariate-panel pass — the measurement behind every completeness number
      in the paper — runs at reasoning effort "low", the cheapest setting, while a HIGHER setting was
      reserved for a secondary field. That is backwards, and the plausible failure mode of a low-effort
      pass (missing a value buried in a baseline table) scores an item 0 when it was in fact reported.
      Every such miss inflates non-reporting, which is the direction of the paper's conclusion. So if a
      bias exists it flatters us, and we should find it before a reviewer does.

  D1 (repeatability). The instrument is stochastic and was run ONCE. Re-running the identical
      configuration measures how much of any observed difference is just noise, which is also the
      yardstick that makes the D2 comparison interpretable.

Design. A fixed, seeded random sample of the analyzable cohort. For each paper, two fresh panel calls:
one at the ORIGINAL settings (repeat) and one at HIGH effort. Compared against the scores already on
disk, that gives repeat-vs-original (noise) and high-vs-original (effort), on the same papers.

SAFETY. This NEVER writes to data/extractions/. The primary extraction is the baseline of the comparison;
overwriting it would destroy the thing being measured. Everything lands in data/reextract/.

    uv run python tools/reextract_effort.py prepare [--n 150] [--seed 20260815]
    uv run python tools/reextract_effort.py submit
    uv run python tools/reextract_effort.py poll
    uv run python tools/reextract_effort.py compare
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from clad_audit.extract import (  # noqa: E402
    SYSTEM, _json_from, build_prompt_panel, openai_text, paper_text,
)
from clad_audit.panel import ITEMS  # noqa: E402

BASE = "https://api.openai.com/v1"
MODEL = "gpt-5.6-luna"
OUT = ROOT / "data" / "reextract"
REQ = OUT / "requests.jsonl"
STATE = OUT / "state.json"
RESULTS = OUT / "results.jsonl"
SAMPLE = OUT / "sample.json"
MIN_SET = ("cmv_dr", "hla_mismatch", "maintenance_is", "acr", "amr")
PANEL_KEYS = [i.key for i in ITEMS if i.tier in "BCD"]     # what build_prompt_panel actually scores


def _hdr(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _body(prompt: str, effort: str, max_out: int = 8000) -> dict:
    """The original request body, with reasoning effort as the ONLY thing that varies.

    max_out is 8000 to match the production call exactly. That is not enough headroom at HIGH effort,
    where reasoning is billed against the same output budget: 43 of 150 high-effort calls in the first
    round returned `incomplete: max_output_tokens` with truncated JSON. The retry path raises it, which
    is a departure from the production body but the only way to observe the high-effort scores at all.
    """
    return {
        "model": MODEL,
        "input": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "reasoning": {"effort": effort},
        "text": {"verbosity": "low", "format": {"type": "json_object"}},
        "max_output_tokens": max_out,
    }


def _truncated_high(path: Path) -> list[str]:
    """pmids whose HIGH-effort call was cut off at max_output_tokens (so produced no usable scores)."""
    out = []
    for line in path.open():
        if not line.strip():
            continue
        rec = json.loads(line)
        pmid, variant = rec["custom_id"].split("::")
        body = (rec.get("response") or {}).get("body") or {}
        if variant == "high" and (body.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
            out.append(pmid)
    return out


def retry(max_out: int) -> None:
    """Rebuild only the truncated high-effort calls, with a larger output budget."""
    pmids = _truncated_high(RESULTS)
    if not pmids:
        print("  nothing truncated — no retry needed")
        return
    # Keep the completed results; the retry file is merged into them after polling.
    (OUT / "results_round1.jsonl").write_text(RESULTS.read_text())
    with REQ.open("w") as f:
        for pmid in pmids:
            prompt = build_prompt_panel(paper_text(pmid))
            f.write(json.dumps({
                "custom_id": f"{pmid}::high", "method": "POST", "url": "/v1/responses",
                "body": _body(prompt, "high", max_out),
            }) + "\n")
    print(f"  {len(pmids)} truncated high-effort calls rebuilt at max_output_tokens={max_out:,} -> {REQ}")
    print("  next: submit, then poll, then merge")


def merge() -> None:
    """Fold retry results into round 1, preferring a parsed retry over a truncated original."""
    keep: dict[str, str] = {}
    for path in (OUT / "results_round1.jsonl", RESULTS):
        if not path.exists():
            continue
        for line in path.open():
            if not line.strip():
                continue
            rec = json.loads(line)
            body = (rec.get("response") or {}).get("body") or {}
            truncated = (body.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
            cid = rec["custom_id"]
            if cid not in keep or not truncated:      # a usable result always beats a truncated one
                keep[cid] = line if line.endswith("\n") else line + "\n"
    (OUT / "results_merged.jsonl").write_text("".join(keep.values()))
    print(f"  merged {len(keep)} results -> {OUT / 'results_merged.jsonl'}")


def prepare(n: int, seed: int) -> None:
    frame = ROOT / "data" / "analysis_frame.csv"
    import csv
    with frame.open(newline="", encoding="utf-8") as fh:
        pmids = [r["pmid"].strip() for r in csv.DictReader(fh)]
    # Only papers whose text still loads and whose original scores are on disk to compare against.
    have = {p.stem for p in (ROOT / "data" / "extractions").glob("*.json")}
    pmids = [p for p in pmids if p in have]
    rng = random.Random(seed)
    sample = sorted(rng.sample(pmids, min(n, len(pmids))))
    OUT.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(json.dumps({"seed": seed, "n": len(sample), "pmids": sample}, indent=2))

    written = skipped = 0
    with REQ.open("w") as f:
        for pmid in sample:
            try:
                text = paper_text(pmid)
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            prompt = build_prompt_panel(text)
            for variant, effort in (("repeat", "low"), ("high", "high")):
                f.write(json.dumps({
                    "custom_id": f"{pmid}::{variant}", "method": "POST", "url": "/v1/responses",
                    "body": _body(prompt, effort),
                }) + "\n")
                written += 1
    approx = sum(len(json.loads(l)["body"]["input"][1]["content"]) for l in REQ.open()) // 4
    print(f"  sample: {len(sample)} papers (seed {seed}), {skipped} skipped for missing text")
    print(f"  requests: {written} ({len(sample)} x repeat/high)  ->  {REQ}")
    print(f"  approx input tokens: {approx:,} (batch API, 50% discount)")


def submit(key: str) -> None:
    up = requests.post(f"{BASE}/files", headers={"Authorization": f"Bearer {key}"},
                       files={"file": (REQ.name, REQ.open("rb"))}, data={"purpose": "batch"}, timeout=300)
    up.raise_for_status()
    fid = up.json()["id"]
    r = requests.post(f"{BASE}/batches", headers=_hdr(key), timeout=60, json={
        "input_file_id": fid, "endpoint": "/v1/responses", "completion_window": "24h"})
    r.raise_for_status()
    bid = r.json()["id"]
    STATE.write_text(json.dumps({"batch": bid, "file": fid}, indent=2))
    print(f"  submitted batch {bid}")


def poll(key: str, every: int) -> None:
    bid = json.loads(STATE.read_text())["batch"]
    while True:
        r = requests.get(f"{BASE}/batches/{bid}", headers=_hdr(key), timeout=60).json()
        st, cts = r.get("status"), r.get("request_counts") or {}
        print(f"  {st}: {cts.get('completed', 0)}/{cts.get('total', 0)} "
              f"(failed {cts.get('failed', 0)})", flush=True)
        if st in ("completed", "failed", "expired", "cancelled"):
            fid = r.get("output_file_id")
            if fid:
                out = requests.get(f"{BASE}/files/{fid}/content",
                                   headers={"Authorization": f"Bearer {key}"}, timeout=300).text
                RESULTS.write_text(out)
                print(f"  wrote {len(out.splitlines())} results -> {RESULTS}")
            return
        time.sleep(every)


def _scores_from(doc: dict) -> dict:
    items = doc.get("items") or doc
    out = {}
    for k in PANEL_KEYS:
        v = items.get(k)
        if isinstance(v, dict):
            out[k] = v.get("score")
    return out


def compare() -> None:
    """repeat-vs-original = noise; high-vs-original = the effect of reasoning effort."""
    got: dict[str, dict] = defaultdict(dict)
    src = OUT / "results_merged.jsonl"
    src = src if src.exists() else RESULTS
    for line in src.open():
        if not line.strip():
            continue
        rec = json.loads(line)
        pmid, variant = rec["custom_id"].split("::")
        body = (rec.get("response") or {}).get("body") or {}
        try:
            got[pmid][variant] = _scores_from(_json_from(openai_text(body)))
        except Exception:  # noqa: BLE001
            pass

    def norm(s):
        return {0: 0, 1: 1, 2: 2, "0": 0, "1": 1, "2": 2}.get(s)

    rows = []
    for pmid, v in got.items():
        orig_doc = json.loads((ROOT / "data" / "extractions" / f"{pmid}.json").read_text())
        orig = _scores_from(orig_doc)
        for variant in ("repeat", "high"):
            if variant not in v:
                continue
            for k in PANEL_KEYS:
                a, b = norm(orig.get(k)), norm(v[variant].get(k))
                if a is None or b is None:
                    continue
                rows.append({"pmid": pmid, "key": k, "variant": variant, "orig": a, "new": b})

    import csv
    with (OUT / "comparison.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pmid", "key", "variant", "orig", "new"])
        w.writeheader()
        w.writerows(rows)

    for variant in ("repeat", "high"):
        sub = [r for r in rows if r["variant"] == variant]
        if not sub:
            continue
        same = sum(r["orig"] == r["new"] for r in sub)
        up = sum(r["new"] > r["orig"] for r in sub)
        down = sum(r["new"] < r["orig"] for r in sub)
        # The direction that matters: an item scored 0 originally that the new pass finds reported is a
        # FALSE NOT-REPORTED in the published numbers, and inflates the paper's headline.
        rescued = sum(r["orig"] == 0 and r["new"] > 0 for r in sub)
        lost = sum(r["orig"] > 0 and r["new"] == 0 for r in sub)
        print(f"\n  {variant} vs original  (n = {len(sub):,} item-scores, {len({r['pmid'] for r in sub})} papers)")
        print(f"    identical         : {same:,} ({100*same/len(sub):.1f}%)")
        print(f"    higher / lower    : {up:,} / {down:,}")
        print(f"    0 -> reported     : {rescued:,} ({100*rescued/len(sub):.2f}%)  <- false not-reported")
        print(f"    reported -> 0     : {lost:,} ({100*lost/len(sub):.2f}%)")
        ms = [r for r in sub if r["key"] in MIN_SET]
        if ms:
            msr = sum(r["orig"] == 0 and r["new"] > 0 for r in ms)
            print(f"    minimum set only  : {sum(r['orig']==r['new'] for r in ms):,}/{len(ms):,} identical, "
                  f"{msr} false not-reported")
    print(f"\n  per-score detail -> {OUT / 'comparison.csv'}")


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "submit", "poll", "compare", "retry", "merge"])
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20260815)
    ap.add_argument("--every", type=int, default=60)
    ap.add_argument("--max-out", type=int, default=24000)
    a = ap.parse_args()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if a.cmd == "prepare":
        prepare(a.n, a.seed)
    elif a.cmd == "submit":
        if not key:
            raise SystemExit("OPENAI_API_KEY missing")
        submit(key)
    elif a.cmd == "poll":
        if not key:
            raise SystemExit("OPENAI_API_KEY missing")
        poll(key, a.every)
    elif a.cmd == "retry":
        retry(a.max_out)
    elif a.cmd == "merge":
        merge()
    else:
        compare()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
