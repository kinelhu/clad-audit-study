"""Batch extraction via the OpenAI Batch API (/v1/responses, 50% discount).

The job is far larger than the org's enqueued-token limit, so we CHUNK it. MANY chunks may be open at
once: the cap is on TOTAL ENQUEUED TOKENS, not on the number of batches (see MAX_ENQUEUED). Both the
chunk size and the cap are env-overridable, because the cap scales with the OpenAI usage tier.

    uv run python -m clad_audit.batch prepare      # build data/batch/requests.jsonl
    uv run python -m clad_audit.batch run          # chunk + submit→poll→retrieve, concurrent, resumable
    uv run python -m clad_audit.batch status       # summarise chunk progress
    BATCH_MAX_ENQUEUED=8000000 uv run python -m clad_audit.batch run     # after a tier upgrade

`run` is resumable: completed chunks are skipped, in-flight chunks resume polling, failed chunks resubmit.
A/B of the same paper are always kept in the same chunk (retrieve needs both to save a paper).

OPERATIONAL NOTES (learned the hard way, 2026-08-12 — keep these):

  * Enqueueing is not processing. 13 batches were accepted at once (7.6M tokens), but OpenAI appeared
    to work through only ~3 concurrently. Submitting more buys queue position and fault isolation,
    NOT parallel throughput. Small chunks are still worth it: a stall then costs one chunk, not the job.

  * Batches stall in two distinct ways, and the right response differs:
      - stuck at N-1 of N (a tail straggler): the batch is working; CANCEL, then retrieve — the
        partial output file holds everything that finished. Salvaged 24+20 papers this way.
      - stuck at exactly 0 of N: the batch is wedged and will sit there indefinitely. Cancelling
        salvages nothing, so cancel and RESUBMIT the same chunk as a fresh batch; a resubmission
        started returning results within two minutes where the original had done nothing in 15.
    To resubmit: delete that chunk's entry from state.json and re-run — `run` submits a new batch.

  * Cancellation is asynchronous and routinely takes 10-30 min, well past OpenAI's documented 10.
    Do not block on it. For a small remainder the sync path (clad_audit.extract --pmids) is faster
    end-to-end than waiting on any batch cycle.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict

import requests
from dotenv import load_dotenv

from .config import DATA_DIR, PROJECT_ROOT
from .extract import (
    DEFAULT_MODELS,
    EXTRACT_DIR,
    FULLTEXT_DIR,
    _json_from,
    build_prompt_panel,
    build_prompt_profile,
    finalize,
    load_design_meta,
    openai_request_body,
    openai_text,
    paper_text,
)

BASE = "https://api.openai.com/v1"
BATCH_DIR = DATA_DIR / "batch"
REQ_FILE = BATCH_DIR / "requests.jsonl"
CHUNK_DIR = BATCH_DIR / "chunks"
STATE_FILE = BATCH_DIR / "state.json"
TOKEN_BUDGET = int(os.environ.get("BATCH_TOKEN_BUDGET", 600_000))    # per chunk
# Total tokens in flight across ALL open batches. 1,800,000 is the safe default under a TIER 1 org cap
# of 2,000,000. The cap scales with the OpenAI usage tier, so raise it via the env var after a tier
# upgrade rather than editing this file:  BATCH_MAX_ENQUEUED=8000000 uv run python -m clad_audit.batch run
MAX_ENQUEUED = int(os.environ.get("BATCH_MAX_ENQUEUED", 1_800_000))
# The cap is on ENQUEUED TOKENS, not on the number of batches: several batches may be open at once
# provided their combined token count stays under it. Running 3x600k instead of 1x1.5M does not raise
# the throughput ceiling (the same volume is queued either way) — the gain is FAULT ISOLATION. A single
# hung request blocks its whole batch until the 24h window expires; with one big chunk that stalls
# every remaining paper behind it, as happened on 2026-08-12 (chunk 0 sat at 135/136 for hours while
# 7 further chunks waited). Smaller concurrent chunks bound the blast radius to one chunk.
TERMINAL_BAD = {"failed", "expired", "cancelled"}


def _hdr(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "content-type": "application/json"}


def _fulltext_pmids() -> list[str]:
    return sorted({p.stem for p in FULLTEXT_DIR.glob("*.pdf")}
                  | {p.stem for p in FULLTEXT_DIR.glob("*.xml")}
                  | {p.stem for p in FULLTEXT_DIR.glob("*.txt")})


def _req_tokens(line: str) -> int:
    d = json.loads(line)
    return sum(len(m["content"]) for m in d["body"]["input"]) // 4


def prepare(model: str, redo: bool) -> None:
    done = {p.stem for p in EXTRACT_DIR.glob("*.json")}
    pmids = [p for p in _fulltext_pmids() if redo or p not in done]
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with REQ_FILE.open("w") as f:
        for pmid in pmids:
            try:
                text = paper_text(pmid)
            except Exception:  # noqa: BLE001
                continue
            for call, builder in (("A", build_prompt_profile), ("B", build_prompt_panel)):
                f.write(json.dumps({
                    "custom_id": f"{pmid}::{call}", "method": "POST", "url": "/v1/responses",
                    "body": openai_request_body(builder(text), model),
                }) + "\n")
                n += 1
    print(f"wrote {n} requests ({len(pmids)} papers × 2) → {REQ_FILE}")


def chunk() -> list:
    """Split requests.jsonl into chunk files, keeping each paper's A+B together, under TOKEN_BUDGET."""
    papers: dict[str, list[str]] = defaultdict(list)
    for line in REQ_FILE.open():
        pmid = json.loads(line)["custom_id"].split("::")[0]
        papers[pmid].append(line)
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    for old in CHUNK_DIR.glob("chunk_*.jsonl"):
        old.unlink()
    # Re-chunking invalidates every chunk INDEX, and state.json is keyed by index. Carrying the old
    # state over makes `run` skip the new chunks as "done" — silently extracting nothing (hit on the
    # 2026-08-12 wave: 14 fresh chunks, all skipped against the previous job's state). Archive + reset.
    if STATE_FILE.exists():
        STATE_FILE.replace(STATE_FILE.with_suffix(".json.prev"))
        print(f"re-chunked: previous state archived to {STATE_FILE.with_suffix('.json.prev').name}")
    chunks, cur, cur_tok = [], [], 0
    for lines in papers.values():
        ptok = sum(_req_tokens(x) for x in lines)
        if cur and cur_tok + ptok > TOKEN_BUDGET:
            chunks.append(cur)
            cur, cur_tok = [], 0
        cur.extend(lines)
        cur_tok += ptok
    if cur:
        chunks.append(cur)
    paths = []
    for i, lines in enumerate(chunks):
        p = CHUNK_DIR / f"chunk_{i:03d}.jsonl"
        p.write_text("".join(lines))
        paths.append(p)
    print(f"split into {len(paths)} chunks (≤{TOKEN_BUDGET:,} tokens each)")
    return paths


def _retry(fn, tries: int = 5, base: float = 3):
    """Retry a network op on any transient error with exponential backoff."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — broken pipe / timeout / 5xx
            if i == tries - 1:
                raise
            print(f"    net retry {i + 1}/{tries - 1}: {type(e).__name__}", flush=True)
            time.sleep(base * (2 ** i))


def _submit_file(key: str, path) -> str:
    def upload() -> str:
        with path.open("rb") as f:  # reopen each attempt so retries re-read the file
            r = requests.post(f"{BASE}/files", headers={"Authorization": f"Bearer {key}"},
                              files={"file": (path.name, f)}, data={"purpose": "batch"}, timeout=180)
        r.raise_for_status()
        return r.json()["id"]

    fid = _retry(upload)

    def create() -> str:
        r = requests.post(f"{BASE}/batches", headers=_hdr(key),
                          json={"input_file_id": fid, "endpoint": "/v1/responses",
                                "completion_window": "24h"}, timeout=60)
        r.raise_for_status()
        return r.json()["id"]

    return _retry(create)


def _get_batch(key: str, bid: str) -> dict:
    def fn() -> dict:
        r = requests.get(f"{BASE}/batches/{bid}", headers=_hdr(key), timeout=60)
        r.raise_for_status()
        return r.json()

    return _retry(fn)


def _retrieve_batch(key: str, bid: str, dm: dict) -> int:
    j = _get_batch(key, bid)
    if not j.get("output_file_id"):
        return 0
    out = _retry(lambda: requests.get(
        f"{BASE}/files/{j['output_file_id']}/content",
        headers={"Authorization": f"Bearer {key}"}, timeout=180)).text
    parts: dict[str, dict] = defaultdict(dict)
    for line in out.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        pmid, call = rec["custom_id"].split("::")
        body = (rec.get("response") or {}).get("body") or {}
        try:
            parts[pmid][call] = _json_from(openai_text(body))
        except Exception:  # noqa: BLE001
            pass
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for pmid, cc in parts.items():
        if "A" in cc and "B" in cc:
            (EXTRACT_DIR / f"{pmid}.json").write_text(
                json.dumps(finalize(pmid, cc["A"], cc["B"], dm), indent=2, ensure_ascii=False))
            saved += 1
    return saved


def _chunk_tokens(path) -> int:
    """Enqueued-token cost of a chunk file — used to keep concurrent batches under MAX_ENQUEUED."""
    return sum(_req_tokens(line) for line in path.open() if line.strip())


def _load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def _save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=2))


def run(key: str, poll: int) -> None:
    if not key:
        raise SystemExit("OPENAI_API_KEY missing")
    # Re-chunk when the chunks are missing OR stale: a fresh `prepare` rewrites requests.jsonl, and
    # reusing chunks built from the PREVIOUS request set would run the wrong (already-extracted) papers.
    paths = sorted(CHUNK_DIR.glob("chunk_*.jsonl"))
    stale = paths and REQ_FILE.exists() and REQ_FILE.stat().st_mtime > max(p.stat().st_mtime for p in paths)
    if not paths or stale:
        if stale:
            print("requests.jsonl is newer than the chunks — re-chunking")
        chunk()
        paths = sorted(CHUNK_DIR.glob("chunk_*.jsonl"))
    dm = load_design_meta()
    state = _load_state()
    print(f"{len(paths)} chunks; already done: {sum(1 for v in state.values() if v.get('status')=='done')}")

    def _finish(i: int, bid: str, s: str) -> None:
        """Retrieve and close out a chunk whose batch reached ANY terminal state.

        A cancelled or expired batch still exposes an output_file_id holding every request that DID
        finish, so we always attempt retrieval — the previous code only retrieved on 'completed' and
        silently discarded that partial work. The chunk is then marked done regardless: re-submitting
        it would re-run the papers already extracted. Stragglers are picked up by the next
        `prepare` (it selects full-text pmids with no extraction), which is the cheap, correct retry.
        """
        saved = _retrieve_batch(key, bid, dm)
        state[str(i)] = {"batch_id": bid, "status": "done", "batch_status": s, "saved": saved}
        _save_state(state)
        note = "" if s == "completed" else f" (batch {s} — partial results kept; re-run prepare for the rest)"
        print(f"chunk {i}: DONE, saved {saved}{note}", flush=True)

    pending = [i for i in range(len(paths)) if state.get(str(i), {}).get("status") != "done"]
    inflight: dict[int, tuple[str, int]] = {}          # chunk idx -> (batch_id, tokens enqueued)
    for i in list(pending):                             # resume batches already open from a prior run
        st = state.get(str(i), {})
        if st.get("batch_id"):
            inflight[i] = (st["batch_id"], _chunk_tokens(paths[i]))
            pending.remove(i)
            print(f"chunk {i}: resuming {st['batch_id']}")

    while pending or inflight:
        while pending:                                  # fill the queue up to MAX_ENQUEUED
            i = pending[0]
            tok = _chunk_tokens(paths[i])
            if inflight and sum(t for _, t in inflight.values()) + tok > MAX_ENQUEUED:
                break
            pending.pop(0)
            try:
                bid = _submit_file(key, paths[i])
            except Exception as e:  # noqa: BLE001 — a submit failure must not kill the run
                # Most often "enqueued token limit reached": the org cap is lower than MAX_ENQUEUED
                # thinks. That is a WAIT condition, not a failure — put the chunk back and retry once
                # something in flight drains, instead of silently dropping it from this run.
                pending.insert(0, i)
                print(f"chunk {i}: submit deferred ({type(e).__name__}: {str(e)[:120]})", flush=True)
                if not inflight:
                    time.sleep(poll)   # nothing draining; back off rather than hot-loop
                break
            inflight[i] = (bid, tok)
            state[str(i)] = {"batch_id": bid, "status": "submitted"}
            _save_state(state)
            print(f"chunk {i}: submitted {bid} ({tok:,} tok; {sum(t for _, t in inflight.values()):,} in flight)")

        for i, (bid, _tok) in list(inflight.items()):
            try:
                j = _get_batch(key, bid)
                s = j["status"]
            except Exception as e:  # noqa: BLE001 — transient poll error, try again next cycle
                print(f"chunk {i}: poll error {type(e).__name__} — retrying", flush=True)
                continue
            if s == "completed" or s in TERMINAL_BAD:
                del inflight[i]
                try:
                    _finish(i, bid, s)
                except Exception as e:  # noqa: BLE001
                    print(f"chunk {i}: RETRIEVE FAILED {type(e).__name__}: {e} — re-run to retry", flush=True)
            else:
                print(f"  chunk {i}: {s} {j.get('request_counts')}", flush=True)
        if inflight:
            time.sleep(poll)

    total = len(list(EXTRACT_DIR.glob("*.json")))
    print(f"\nrun complete. extractions on disk: {total}")


def status(key: str) -> None:
    state = _load_state()
    paths = sorted(CHUNK_DIR.glob("chunk_*.jsonl"))
    done = sum(1 for v in state.values() if v.get("status") == "done")
    saved = sum(v.get("saved", 0) for v in state.values())
    print(f"chunks: {done}/{len(paths)} done | papers extracted: {saved} | files on disk: {len(list(EXTRACT_DIR.glob('*.json')))}")
    for i in range(len(paths)):
        st = state.get(str(i), {})
        line = f"  chunk {i:03d}: {st.get('status','pending')}"
        if st.get("batch_id") and st.get("status") not in ("done",):
            line += f" ({_get_batch(key, st['batch_id'])['status']})" if key else ""
        print(line)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "chunk", "run", "status"])
    ap.add_argument("--model", default=DEFAULT_MODELS["openai"])
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--poll", type=int, default=60, help="seconds between status polls in run")
    args = ap.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY", "").strip()

    if args.cmd == "prepare":
        prepare(args.model, args.redo)
    elif args.cmd == "chunk":
        chunk()
    elif args.cmd == "run":
        run(key, args.poll)
    elif args.cmd == "status":
        status(key)


if __name__ == "__main__":
    main()
