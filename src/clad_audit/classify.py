"""Study classifier (title + abstract) — flags non-clinical studies and cleans intervention coding.

The discovery query pulled preclinical work (animal / in-vitro / mechanistic) that cannot report human
covariates and would inflate 'not reported'. This pass classifies each extracted study from its title and
abstract into species / clinical, and (for interventional studies) a controlled-vocabulary intervention
class and intent. Cheap (short input, gpt-5.6-luna). Resumable JSONL cache.

    uv run python -m clad_audit.classify        -> data/classifications.csv

Downstream: build_frame joins it; the analysis restricts the analyzable cohort to human clinical studies.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import CORPUS_CSV, DATA_DIR, PROJECT_ROOT
from .extract import DEFAULT_MODELS, OPENAI_URL, _json_from, openai_text

OUT = DATA_DIR / "classifications.jsonl"
CLASS_CSV = DATA_DIR / "classifications.csv"
SYSTEM = ("You classify biomedical studies from their title and abstract only. Be strict about human vs "
          "non-human. Return ONLY a single JSON object.")
VOCAB = ["Extracorporeal photopheresis", "Azithromycin / macrolide", "mTOR inhibitor", "Cell therapy",
         "Antifibrotic", "Antireflux surgery", "Total lymphoid irradiation", "Inhaled ciclosporin",
         "Antibody / biologic", "Induction agent", "CMV prophylaxis / antiviral", "Montelukast", "Statin",
         "Aerosolised / inhaled other", "Surgical / procedural", "Other pharmacological", "Not specified"]


def build_prompt(title: str, abstract: str) -> str:
    """Independent title+abstract classification. Design + a grounded interventional flag are decided HERE
    (the abstract is the dense, reliable signal for study type), NOT inherited from the full-text pass."""
    v = "; ".join(VOCAB)
    return f"""Classify this study from its title and abstract alone.

STUDY DESIGN — what kind of study is this (from the abstract's own words)?
  rct                  = randomized controlled trial
  prospective_cohort   = prospectively enrolled / followed forward per protocol
  retrospective_cohort = existing records/charts reviewed after the fact
  registry             = analysis of a named organ registry (UNOS/OPTN/SRTR/ISHLT/Eurotransplant/national DB)
  cross_sectional | other

EVALUATES AN INTERVENTION — does the study assess the effect of a SPECIFIC therapy, procedure, or protocol
  change on outcomes (a drug, surgery, device, IS regimen, prophylaxis, EVLP, etc.), by randomization,
  prospective assignment, OR a retrospective treated-vs-comparison design where that intervention IS the
  study's subject? false for a purely descriptive/observational cohort with no specific intervention as its focus.
  evaluates_intervention=true REQUIRES intervention_evidence: a verbatim abstract phrase naming the tested
  intervention (e.g. "randomized to azithromycin vs placebo", "effect of antireflux surgery on CLAD"). If you
  cannot quote that, evaluates_intervention=false and intervention_evidence="".

Return exactly this JSON:
{{"species": "human | animal | in_vitro | ex_vivo_human | mixed",
  "clinical": true or false,   // true ONLY for a study of human patients; false for animal/in-vitro/ex-vivo/mechanistic
  "study_design": "rct | prospective_cohort | retrospective_cohort | registry | cross_sectional | other",
  "study_design_evidence": "verbatim design phrase from the abstract, or ''",
  "study_type": "clinical_cohort | trial | registry | mechanistic_translational | case_report_series | methods_or_review",
     // ELIGIBILITY axis (orthogonal to design). clinical_cohort/trial/registry = patient-level clinical study
     //   where a covariate panel is expected. mechanistic_translational = biomarker/-omics/immunology/imaging
     //   MECHANISM study (CLAD is the outcome of a mechanism analysis, not a cohort characterisation).
     //   case_report_series = n<10 or single-case. methods_or_review = statistical/modelling methods, or a review.
  "evaluates_intervention": true or false,
  "intervention_evidence": "verbatim intervention phrase from the abstract, or ''",
  "intervention_class": one of [{v}] or "",   // "" if evaluates_intervention is false
  "intent": "prevention | treatment_established_clad | na",
  "sample_n": integer or null,   // number of human subjects/recipients studied, IF the abstract states it (null if not)
  "sample_n_evidence": "verbatim phrase stating the N, or ''"}}

Only report sample_n if the abstract actually gives it; do not infer or guess. This is title+abstract only —
report what is STATED, never what the study "should" contain.

TITLE: {title}
ABSTRACT: {abstract[:4000]}
"""


def _reconcile(rec: dict) -> dict:
    """Grounding guardrail: an interventional flag survives only with a verbatim abstract quote."""
    if rec.get("evaluates_intervention") in (True, "true") and not str(rec.get("intervention_evidence", "")).strip():
        rec["evaluates_intervention"] = False
    if rec.get("evaluates_intervention") not in (True, "true"):
        rec["intervention_class"] = ""
        if rec.get("intent") not in ("prevention", "treatment_established_clad"):
            rec["intent"] = "na"
    return rec


def _body(prompt: str, model: str) -> dict:
    """The /v1/responses request body — shared by the sync call and the Batch JSONL."""
    return {"model": model,
            "input": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "reasoning": {"effort": "low"}, "text": {"verbosity": "low", "format": {"type": "json_object"}},
            "max_output_tokens": 700}


def _call(prompt: str, model: str, key: str) -> dict:
    body = _body(prompt, model)
    last = None
    for attempt in range(5):                                  # absorb transient network blips (backoff)
        try:
            r = requests.post(OPENAI_URL, headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                              json=body, timeout=120)
            r.raise_for_status()
            return _json_from(openai_text(r.json()))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _classify_one(p: str, title: str, abstract: str, model: str, key: str) -> dict:
    rec = {"pmid": p}
    try:
        rec.update(_reconcile(_call(build_prompt(title, abstract), model, key)))
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)
    return rec


def _done_pmids() -> set:
    if not OUT.exists():
        return set()
    return {r["pmid"] for l in OUT.open() if l.strip() and "error" not in (r := json.loads(l))}


def _write_csv() -> None:
    recs: dict[str, dict] = {}
    for l in OUT.open():
        if l.strip():
            r = json.loads(l)
            if r["pmid"] not in recs or "error" not in r:
                recs[r["pmid"]] = r
    df = pd.DataFrame([r for r in recs.values() if "error" not in r])
    df.to_csv(CLASS_CSV, index=False)
    print(f"\nwrote {len(df)} → {CLASS_CSV}")
    if "clinical" in df:
        print(f"  clinical: {(df['clinical'] == True).sum()} | interventional: {(df.get('evaluates_intervention') == True).sum()}")


def run_batch(key: str, model: str, poll: int = 60) -> None:
    """Classify the corpus via the OpenAI Batch API (~50% cheaper, off-machine). One request per pmid;
    chunked under the enqueued-token cap; reuses batch.py submit/poll primitives. Resumable via _done_pmids."""
    from .batch import BASE, TERMINAL_BAD, TOKEN_BUDGET, _get_batch, _retry, _submit_file
    corpus = pd.read_csv(CORPUS_CSV, dtype={"pmid": str}).set_index("pmid")
    todo = [p for p in corpus.index if p not in _done_pmids()]
    print(f"batch: {len(todo)} to classify")
    if not todo:
        return _write_csv()
    reqdir = DATA_DIR / "batch"; reqdir.mkdir(parents=True, exist_ok=True)
    # build one request per pmid, chunk under the token budget
    chunks, cur, tok = [], [], 0
    for p in todo:
        title = str(corpus.loc[p, "title"]) if pd.notna(corpus.loc[p, "title"]) else ""
        abstract = str(corpus.loc[p, "abstract"]) if pd.notna(corpus.loc[p, "abstract"]) else ""
        line = json.dumps({"custom_id": p, "method": "POST", "url": "/v1/responses",
                           "body": _body(build_prompt(title, abstract), model)})
        t = len(line) // 4
        if cur and tok + t > TOKEN_BUDGET:
            chunks.append(cur); cur, tok = [], 0
        cur.append(line); tok += t
    if cur:
        chunks.append(cur)
    print(f"  {len(chunks)} chunk(s)")
    with OUT.open("a") as out:
        for i, ch in enumerate(chunks):
            path = reqdir / f"classify_chunk_{i:02d}.jsonl"; path.write_text("\n".join(ch))
            bid = _submit_file(key, path); print(f"  chunk {i}: submitted {bid}", flush=True)
            while True:
                j = _get_batch(key, bid); s = j["status"]
                if s == "completed" or s in TERMINAL_BAD:
                    break
                print(f"    chunk {i}: {s} {j.get('request_counts')}", flush=True); time.sleep(poll)
            if s != "completed":
                print(f"  chunk {i}: {s} — re-run to retry"); continue
            content = _retry(lambda j=j: requests.get(f"{BASE}/files/{j['output_file_id']}/content",
                             headers={"Authorization": f"Bearer {key}"}, timeout=180)).text
            for line in content.splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line); pmid = rec["custom_id"]
                body = (rec.get("response") or {}).get("body") or {}
                try:
                    r = _reconcile(_json_from(openai_text(body))); r["pmid"] = pmid
                except Exception as e:  # noqa: BLE001
                    r = {"pmid": pmid, "error": str(e)}
                out.write(json.dumps(r) + "\n"); out.flush()
    _write_csv()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", action="store_true", help="use the OpenAI Batch API (~50%% cheaper, off-machine)")
    ap.add_argument("--workers", type=int, default=12, help="concurrent requests for the sync path")
    args = ap.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY missing")
    model = DEFAULT_MODELS["openai"]
    workers = args.workers
    if args.batch:
        return run_batch(key, model)
    # Classify the WHOLE screened corpus (1,923) from title+abstract — decoupled from the full-text pass.
    # This is authoritative for design / interventional / N and reaches the ~1,050 records without full text.
    corpus = pd.read_csv(CORPUS_CSV, dtype={"pmid": str}).set_index("pmid")
    todo = [p for p in corpus.index if p not in _done_pmids()]
    print(f"{len(corpus) - len(todo)} cached, {len(todo)} to classify (of {len(corpus)} screened records), {workers} workers")

    def txt(p, col):
        return str(corpus.loc[p, col]) if pd.notna(corpus.loc[p, col]) else ""

    # I/O-bound API calls → thread pool. Main thread owns all file writes (results consumed as they
    # complete), so no write lock needed; per-call retry/backoff absorbs rate-limit blips.
    with OUT.open("a") as f, ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_classify_one, p, txt(p, "title"), txt(p, "abstract"), model, key): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            f.write(json.dumps(fut.result()) + "\n")
            f.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", end="\r", flush=True)

    _write_csv()


if __name__ == "__main__":
    main()
