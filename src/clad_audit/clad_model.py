"""Study-level CLAD-model extraction — ONE focused call per paper.

Captures whether a study fitted a MULTIVARIABLE model FOR CLAD (BOS/RAS) and, if so, its covariate list.
Decouples adjustment capture from the fragile per-item grounding in extract.py, which systematically missed
multivariable models (~75 false negatives: a covariate is only credited "adjusted" when the model quotes it
individually, so real multivariable Cox models with a covariate table were recorded as univariable/none).
Validated on a 14-paper probe (recovers the misses; correctly excludes multivariable models fit for a
NON-CLAD outcome — overall survival, mortality; correctly labels univariable-only log-rank studies).

The free-text `covariates` list is mapped to panel keys deterministically in build_frame (controlled keyword
map), which then rebuilds adjustment_set / per-item `adjusted` — replacing the broken grounding.

    uv run python -m clad_audit.clad_model --batch     -> data/clad_models.jsonl / .csv   (Batch API, ~50% off)
    uv run python -m clad_audit.clad_model             -> same via threaded sync calls
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from dotenv import load_dotenv

from .config import DATA_DIR, PROJECT_ROOT
from .extract import DEFAULT_MODELS, OPENAI_URL, _json_from, openai_text, paper_text

# ---------------------------------------------------------------------------
# Deterministic map: free-text covariate string -> panel key (or None for a generic
# demographic/comorbidity that is not a panel item). Ordered; FIRST match wins, so specific
# patterns precede generic ones (e.g. "cmv infection"->cmv_events before "cmv"->cmv_dr;
# "pre-tx dsa" before generic "dsa"; anti-HLA antibodies -> de_novo_dsa before hla_mismatch).
# Tuned against the actual clad_model covariate vocabulary (see scratchpad/test_map.py).
# ---------------------------------------------------------------------------
COVARIATE_MAP = [
    ("cmv_events",       r"\bcmv (infection|disease|viremia|viraemia|event|replication|reactivation)"),
    ("cmv_dr",           r"\bcmv\b|cytomegalovirus"),
    ("pre_tx_dsa",       r"pre.?(tx|transplant).*(dsa|antibod)|preformed|pre.?existing dsa|cpra|\bpra\b|sensitiz"),
    ("de_novo_dsa",      r"de.?novo dsa|dndsa|\bdsa\b|donor.?specific|anti.?hla|hla.?antibod"),
    ("eplet_mm",         r"eplet|pirche|molecular mismatch"),
    ("hla_mismatch",     r"hla mismatch|human leukocyte|mismatch(es)? at|hla.?[abcdrq]|\bhla\b|abdr|a/b/dr"),
    ("nonhla_ab",        r"non.?hla|at1r|etar|collagen v|k.?alpha|kalpha|self.?antigen|mica"),
    ("amr",              r"\bamr\b|antibody.?mediated"),
    ("acr",              r"acute (cellular )?rejection|\bacr\b|\bar\b|a.?score|a.?grade|rejection (score|episode|grade|burden|frequency)|cellular rejection|lymphocytic bronchiolitis|\bb.?grade\b|\bb.?score\b"),
    ("pgd",              r"\bpgd\b|primary graft dysfunction|graft dysfunction"),
    ("induction",        r"induction"),
    ("maintenance_is",   r"maintenance|immunosuppress|tacrolimus|cyclosporin|ciclosporin|calcineurin|\bcni\b|mtor|sirolimus|everolimus|mycophenolate|\bmmf\b|azathioprine|steroid|prednis|\bis regimen\b"),
    ("resp_viral",       r"respiratory (virus|viral)|viral infection|\brsv\b|influenza|rhinovirus|community.?acquired resp"),
    ("colonization",     r"pseudomonas|aspergillus|coloniz|fungal|bacterial"),
    ("gerd",             r"gerd|reflux|aspiration|gastro.?esophageal|gastro.?oesophageal"),
    ("azithromycin",     r"azithromycin|macrolide"),
    ("telomere",         r"telomere"),
    ("antifibrotic",     r"antifibrotic|pirfenidone|nintedanib"),
    ("cni_ipv",          r"intra.?patient variab|coefficient of variation|tacrolimus variab|\bipv\b"),
    ("cyp3a5",           r"cyp3a5|pharmacogenom"),
    ("pre_tx_is",        r"pre.?(tx|transplant).*(immunosupp|is exposure)"),
    ("evlp",             r"evlp|ex.?vivo lung|ex vivo"),
    ("donor_type",       r"donor type|\bdbd\b|\bdcd\b|donation after|brain death|circulatory death|donor cause"),
    ("race_ethnicity",   r"\brace\b|ethnic"),
    ("era",              r"(year|era|period|calendar).*(transplant|transplantation)|transplant (year|era)|accrual|year of"),
    ("center_structure", r"transplant cent|multi.?cent|single.?cent|number of cent|\binstitution\b|transplant location|treating cent"),
    ("procedure",        r"single.?(lung|vs|or bilateral)|bilateral|type of (lung )?transplant|type of ltx|number of lungs|transplant type|double lung|type of transplant"),
    ("indication_mix",   r"diagnos|indication|native lung|underlying (dis|diagnos)|primary (dis|diagnos)|cystic fibrosis|pulmonary fibrosis|\bcopd\b|emphysema|\bipf\b|interstitial|\bild\b|disease group|primary disease"),
    ("phenotyping",      r"\bbos\b|\bras\b|phenotype|clad type"),
    ("baseline_fev1",    r"\bfev1\b|baseline lung function|spirometr"),
    ("clad_staging",     r"clad (stage|grade|severity)|severity of clad"),
    ("competing_risk",   r"competing risk"),
]
_COMPILED = [(k, re.compile(p, re.I)) for k, p in COVARIATE_MAP]


def map_covariate(s: str) -> str | None:
    """One free-text covariate string -> a panel key, or None if it is not a panel item."""
    for k, rx in _COMPILED:
        if rx.search(s):
            return k
    return None


def map_covariates(cov_list) -> list[str]:
    """A study's covariate list -> the sorted unique set of PANEL keys it adjusted for."""
    keys = {k for c in (cov_list or []) if (k := map_covariate(str(c)))}
    return sorted(keys)


# Non-panel canonical confounders (checked AFTER the panel patterns) — for the UNRESTRICTED covariate
# frequency and co-adjustment analyses (build_frame emits data/covariate_adjust.csv). Panel wins on overlap
# (e.g. "fev1" -> baseline_fev1 via the panel map, not lung_function here).
_EXTRA_MAP = [
    ("age",           r"\bage\b|recipient age|donor age|age at"),
    ("sex",           r"\bsex\b|gender|female|male"),
    ("bmi",           r"\bbmi\b|body mass"),
    ("las",           r"lung allocation|\blas\b"),
    ("ischemic_time", r"ischemi|ischaemi"),
    ("comorbidity",   r"diabet|hypertens|renal|creatinine|dialysis|smoking|coronary|cardiac"),
    ("lung_function", r"\bfvc\b|\btlc\b|dlco|six.?minute|6mwt"),
]
_EXTRA = [(k, re.compile(p, re.I)) for k, p in _EXTRA_MAP]
_EXTRA_LABEL = {"age": "Age", "sex": "Sex / gender", "bmi": "Body mass index", "las": "Lung allocation score",
                "ischemic_time": "Ischemic time", "comorbidity": "Comorbidity", "lung_function": "Lung function"}
CONCEPT_LABEL = {**{it.key: it.label for it in __import__("clad_audit.panel", fromlist=["ITEMS"]).ITEMS}, **_EXTRA_LABEL}


def canon_covariate(s: str) -> str | None:
    """One covariate -> a canonical concept: a panel key, an extra confounder key, or None (unmapped 'other')."""
    for k, rx in _COMPILED:
        if rx.search(s):
            return k
    for k, rx in _EXTRA:
        if rx.search(s):
            return k
    return None


def canon_covariates(cov_list) -> list[str]:
    """A study's covariate list -> sorted unique canonical concepts (panel + extra confounders)."""
    return sorted({k for c in (cov_list or []) if (k := canon_covariate(str(c)))})

# ---------------------------------------------------------------------------
# Covariate-enumeration REFINE pass (grounded, higher effort) for the multivariable studies.
# The base pass under-enumerates covariates from results tables (found e.g. 15996255 capturing 2 of ~4-7).
# This re-runs ONLY the multivariable studies at effort=medium with a table-pointing, grounded prompt: every
# covariate the model lists must appear in `covariates_evidence`, and a deterministic filter drops any that
# don't. Validated: recovers missed covariates without hallucinating (scratchpad/probe_covars2.py).
# ---------------------------------------------------------------------------
REFINE_OUT = DATA_DIR / "clad_covariates.jsonl"
REFINE_CSV = DATA_DIR / "clad_covariates.csv"
REFINE_SYSTEM = ("You extract the EXACT covariate set of a study's multivariable model for CLAD (BOS/RAS) as the "
                 "outcome. Every covariate you list MUST be copied from the paper's own text; never invent one. "
                 "Return ONLY a single JSON object.")
REFINE_PROMPT = '''This study fits a MULTIVARIABLE model for CLAD (BOS/RAS) as the OUTCOME. Enumerate the covariates in that model.

WHERE TO LOOK: the covariates are the variables in the "adjusted"/"multivariable"/"multivariate" hazard-ratio (or
odds-ratio) column of a results TABLE, and/or the variables named in the sentence describing the model ("adjusted for
...", "the multivariable model included ..."). Read BOTH the Methods and the results table. List EVERY covariate in
the multivariable CLAD model.

GROUNDING (critical): every covariate you list MUST appear, in words, inside `covariates_evidence`. Build
`covariates_evidence` by copying VERBATIM the text that names the covariates - the "adjusted for ..." sentence AND/OR
the variable names from the multivariable table's variable column (copy the row labels). Do NOT list any covariate
whose name is not present in `covariates_evidence`.

RULES:
- Only the multivariable model whose OUTCOME is CLAD/BOS/RAS. Ignore models for survival, mortality, or other outcomes.
- Give a category variable once (e.g. "diagnosis", not each level).

Return exactly:
{"covariates": ["verbatim covariate name", ...],
 "stated_n_covariates": integer or null,
 "covariates_evidence": "verbatim text naming ALL listed covariates (the sentence and/or copied table variable column)"}

FULL TEXT:
'''
_STOP = {"the", "of", "and", "or", "in", "at", "on", "a", "an", "to", "for", "group", "status", "type", "score",
         "number", "level", "grade", "vs", "history"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


def _grounded(cov: str, ev: str) -> bool:
    """Keep a covariate only if its distinctive words are present in the evidence text."""
    ev_n = _norm(ev)
    words = [w for w in _norm(cov).split() if len(w) >= 4 and w not in _STOP]
    if not words:
        return _norm(cov).strip() in ev_n
    return sum(w in ev_n for w in words) / len(words) >= 0.6


def _refine_call(text: str, model: str, key: str) -> dict:
    body = {"model": model, "input": [{"role": "system", "content": REFINE_SYSTEM},
            {"role": "user", "content": REFINE_PROMPT + text[:170000]}],
            "reasoning": {"effort": "medium"}, "text": {"verbosity": "low", "format": {"type": "json_object"}},
            "max_output_tokens": 2500}
    last = None
    for attempt in range(5):
        try:
            r = requests.post(OPENAI_URL, headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                              json=body, timeout=300)
            r.raise_for_status()
            return _json_from(openai_text(r.json()))
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(3 * (attempt + 1))
    raise last


def _refine_one(pmid: str, model: str, key: str) -> dict:
    try:
        text = paper_text(pmid)
    except Exception as e:  # noqa: BLE001
        return {"pmid": pmid, "error": f"no text: {e}"}
    try:
        r = _refine_call(text, model, key)
        ev = str(r.get("covariates_evidence", ""))
        kept = [c for c in (r.get("covariates") or []) if _grounded(str(c), ev)]
        return {"pmid": pmid, "covariates": kept, "stated_n_covariates": r.get("stated_n_covariates"),
                "covariates_evidence": ev[:600]}
    except Exception as e:  # noqa: BLE001
        return {"pmid": pmid, "error": str(e)}


def _refine_done() -> set:
    if not REFINE_OUT.exists():
        return set()
    return {r["pmid"] for l in REFINE_OUT.open() if l.strip() and "error" not in (r := json.loads(l))}


def run_refine(key: str, model: str, workers: int = 6) -> None:
    """Re-enumerate covariates (grounded, effort=medium) for the multivariable studies only."""
    cm = pd.read_csv(CSV, dtype={"pmid": str})
    mv = cm.loc[cm["model_type"] == "multivariable", "pmid"].tolist()
    todo = [p for p in mv if p not in _refine_done()]
    print(f"refine: {len(mv)} multivariable studies, {len(todo)} to (re-)enumerate, {workers} workers")
    with REFINE_OUT.open("a") as f, ThreadPoolExecutor(max_workers=workers) as ex:
        for i, fut in enumerate(as_completed([ex.submit(_refine_one, p, model, key) for p in todo]), 1):
            f.write(json.dumps(fut.result()) + "\n"); f.flush()
            if i % 20 == 0:
                print(f"  {i}/{len(todo)}", end="\r", flush=True)
    recs = {}
    for l in REFINE_OUT.open():
        if l.strip():
            r = json.loads(l)
            if r["pmid"] not in recs or "error" not in r:
                recs[r["pmid"]] = r
    rows = [{"pmid": r["pmid"], "covariates": ";".join(r.get("covariates") or []),
             "stated_n_covariates": r.get("stated_n_covariates")} for r in recs.values() if "error" not in r]
    pd.DataFrame(rows).to_csv(REFINE_CSV, index=False)
    n_cov = [len((r.get("covariates") or [])) for r in recs.values() if "error" not in r]
    print(f"\nwrote {len(rows)} -> {REFINE_CSV} | median covariates/study: {sorted(n_cov)[len(n_cov)//2] if n_cov else 0}")


OUT = DATA_DIR / "clad_models.jsonl"
CSV = DATA_DIR / "clad_models.csv"
EXTRACT_DIR = DATA_DIR / "extractions"
MAX_CHARS = 150_000

SYSTEM = ("You determine how a lung-transplant study modelled CLAD as an OUTCOME (CLAD includes BOS and RAS). "
          "Only consider a regression whose OUTCOME is CLAD/BOS/RAS — ignore models for other outcomes such as "
          "overall survival, mortality, or acute rejection. Return ONLY a single JSON object.")

PROMPT = """Determine the study's PRIMARY analysis relating an exposure to CLAD (BOS/RAS) as the outcome.

  model_type:
    "multivariable"    = a regression model for CLAD with 2 or more covariates fitted TOGETHER
                         (multivariable Cox, competing-risks, or logistic; or the "adjusted"/"multivariable"
                         HR/OR column of a table)
    "univariable_only" = ONLY single-covariate associations for CLAD: one-at-a-time HRs/ORs, Kaplan-Meier +
                         log-rank, or the unadjusted column of a table, with NO joint multivariable model
    "none"             = no regression relating any exposure to CLAD (descriptive/baseline only, OR the only
                         multivariable model in the paper is for a DIFFERENT outcome such as survival/mortality)
  method: cox_ph | competing_risk | logistic | km_logrank | other | none
  covariates: the covariates entered in that multivariable CLAD model, verbatim as the paper names them
              (e.g. ["recipient age","sex","CMV mismatch","induction"]); [] unless model_type is multivariable
  n_covariates: integer number of covariates in the multivariable CLAD model, or null
  evidence: ONE verbatim phrase from the paper proving model_type — the sentence naming the multivariable CLAD
            model and/or listing its covariates, or the adjusted-column table caption. "" only if truly absent.

Base model_type on what the paper ACTUALLY fitted for CLAD, not on good practice. A table giving a separate HR
for each variable one at a time is univariable_only. Mark "multivariable" only if 2+ covariates share ONE model
whose outcome is CLAD. Do not invent covariates. Return ONLY the JSON object:
{"model_type":"...","method":"...","covariates":[...],"n_covariates":null,"evidence":"..."}

FULL TEXT:
"""


def _body(text: str, model: str) -> dict:
    """The /v1/responses request body — shared by the sync call and the Batch JSONL."""
    return {"model": model,
            "input": [{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": PROMPT + text[:MAX_CHARS]}],
            "reasoning": {"effort": "low"}, "text": {"verbosity": "low", "format": {"type": "json_object"}},
            "max_output_tokens": 1200}


def _reconcile(rec: dict) -> dict:
    """Guardrail: a covariate list is meaningful only for a multivariable model."""
    if rec.get("model_type") != "multivariable":
        rec["covariates"] = []
        rec["n_covariates"] = None
    return rec


def _call(text: str, model: str, key: str) -> dict:
    last = None
    for attempt in range(5):
        try:
            r = requests.post(OPENAI_URL, headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
                              json=_body(text, model), timeout=300)
            r.raise_for_status()
            return _json_from(openai_text(r.json()))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def _pmids() -> list[str]:
    """Papers with a full-text extraction (the 868 in the analysis frame)."""
    return sorted(p.stem for p in EXTRACT_DIR.glob("*.json"))


def _done() -> set:
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
    rows = []
    for r in recs.values():
        if "error" in r:
            continue
        cov = r.get("covariates") or []
        rows.append({"pmid": r["pmid"], "model_type": r.get("model_type"), "method": r.get("method"),
                     "n_covariates": r.get("n_covariates"), "covariates": ";".join(cov),
                     "evidence": r.get("evidence", "")})
    df = pd.DataFrame(rows)
    df.to_csv(CSV, index=False)
    print(f"\nwrote {len(df)} -> {CSV}")
    if "model_type" in df:
        print("  model_type:", df["model_type"].value_counts().to_dict())


def run_batch(key: str, model: str, poll: int = 60) -> None:
    from .batch import BASE, TERMINAL_BAD, TOKEN_BUDGET, _get_batch, _retry, _submit_file
    todo = [p for p in _pmids() if p not in _done()]
    print(f"batch: {len(todo)} to extract (of {len(_pmids())})")
    if not todo:
        return _write_csv()
    reqdir = DATA_DIR / "batch_clad"; reqdir.mkdir(parents=True, exist_ok=True)
    chunks, cur, tok = [], [], 0
    for p in todo:
        try:
            text = paper_text(p)
        except Exception:  # noqa: BLE001
            continue
        line = json.dumps({"custom_id": p, "method": "POST", "url": "/v1/responses", "body": _body(text, model)})
        t = len(line) // 4
        if cur and tok + t > TOKEN_BUDGET:
            chunks.append(cur); cur, tok = [], 0
        cur.append(line); tok += t
    if cur:
        chunks.append(cur)
    print(f"  {len(chunks)} chunk(s)")
    with OUT.open("a") as out:
        for i, ch in enumerate(chunks):
            path = reqdir / f"clad_chunk_{i:02d}.jsonl"; path.write_text("\n".join(ch))
            bid = _submit_file(key, path); print(f"  chunk {i}: submitted {bid}", flush=True)
            polls = 0
            while True:
                j = _get_batch(key, bid); s = j["status"]
                # Terminal OR a stuck cancel: "cancelling" can linger indefinitely on the platform and must not
                # wedge the run — treat it (and a chunk stuck non-completing past a generous cap) as skip-and-retry.
                if s == "completed" or s in TERMINAL_BAD or s == "cancelling" or polls > 240:
                    break
                print(f"    chunk {i}: {s} {j.get('request_counts')}", flush=True); polls += 1; time.sleep(poll)
            if s != "completed":
                print(f"  chunk {i}: {s} — skipped; re-run clad_model to pick up its papers", flush=True); continue
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
    ap.add_argument("--refine", action="store_true", help="grounded covariate re-enumeration (multivariable studies only)")
    ap.add_argument("--workers", type=int, default=8, help="concurrent requests for the sync path")
    args = ap.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY missing")
    model = DEFAULT_MODELS["openai"]
    if args.refine:
        return run_refine(key, model, workers=min(args.workers, 6))
    if args.batch:
        return run_batch(key, model)
    todo = [p for p in _pmids() if p not in _done()]
    print(f"{len(_pmids()) - len(todo)} cached, {len(todo)} to extract, {args.workers} workers")

    def one(p: str) -> dict:
        try:
            text = paper_text(p)
        except Exception as e:  # noqa: BLE001
            return {"pmid": p, "error": f"no text: {e}"}
        try:
            r = _reconcile(_call(text, model, key)); r["pmid"] = p; return r
        except Exception as e:  # noqa: BLE001
            return {"pmid": p, "error": str(e)}

    with OUT.open("a") as f, ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, fut in enumerate(as_completed([ex.submit(one, p) for p in todo]), 1):
            f.write(json.dumps(fut.result()) + "\n"); f.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", end="\r", flush=True)
    _write_csv()


if __name__ == "__main__":
    main()
