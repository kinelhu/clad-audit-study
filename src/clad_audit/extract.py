"""Stage 5 (prototype) — LLM extraction against the locked codebook.

Reads a paper's full text (PDF via pymupdf), asks Claude to score every panel item
not/partial/full (+N/A for inapplicable conditional items) with a verbatim evidence quote, and
tags the outcome role. min-set-met and the interpretability score are computed in Python (not
trusted to the model) for determinism.

    uv run python -m clad_audit.extract --sample 8                 # run on N random saved PDFs
    uv run python -m clad_audit.extract --pmids 19578518,24146959
    uv run python -m clad_audit.extract --pmids 19578518 --dry-run # text only, no API call

Needs ANTHROPIC_API_KEY in .env. Saves data/extractions/{pmid}.json.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

import fitz  # pymupdf
import requests
from dotenv import load_dotenv

from .config import DATA_DIR, PROJECT_ROOT
from .panel import ITEMS, MIN_SET

# Bump on any change to the panel, prompts, or scoring — stamped into every extraction for reproducibility.
PROTOCOL_VERSION = "clad-audit v0.7 (2026-08-06): v0.6 + registry design reconciliation (metadata registry overrides LLM, like rct)"

FULLTEXT_DIR = DATA_DIR / "fulltext"
EXTRACT_DIR = DATA_DIR / "extractions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/responses"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODELS = {"openai": "gpt-5.6-luna", "anthropic": "claude-sonnet-5"}
MAX_CHARS = 180_000

SYSTEM = (
    "You are a meticulous evidence extractor for a reporting-completeness audit of the lung-transplant "
    "CLAD literature. You judge ONLY what a study reports, never what it should have found. You never "
    "infer a value that is not printed. Every non-zero score must be backed by a verbatim quote copied "
    "from the paper. Return ONLY a single JSON object, no prose."
)


_TIER_NAMES = {"A": "Case-mix/context", "B": "Core immunological", "C": "Non-alloimmune second hits",
               "D": "Novel/emerging", "E": "Outcome ascertainment"}


def _codebook(tiers: str) -> str:
    by_tier: dict[str, list[str]] = {}
    for it in ITEMS:
        if it.tier not in tiers:
            continue
        tag = " [MIN-SET]" if it.min_set else (" [recommended]" if it.recommended else "")
        cond = f"  (CONDITIONAL — score NA only if absent: {it.trigger})" if it.conditional else ""
        by_tier.setdefault(it.tier, []).append(
            f'  - {it.key}{tag}: "{it.label}". full(2)={it.full}. partial(1)={it.partial}.{cond}'
        )
    return "\n".join(f"{t} — {_TIER_NAMES[t]}:\n" + "\n".join(rows) for t, rows in by_tier.items())


_SCORING = """SCORING (per item):
  2 = full   — reported at the granularity in full(2).
  1 = partial— mentioned but below that bar (see partial(1)).
  0 = not reported.
  "NA" = a CONDITIONAL item whose trigger population is absent. If the trigger IS present but the item
         is not reported, score 0 (not NA).

EVIDENCE RULES (strict):
  - A score of 1 or 2 REQUIRES a verbatim evidence_quote that BY ITSELF establishes THIS SPECIFIC item at
    that level. A sentence about a different/adjacent item does NOT count — never borrow/reuse a neighbour's
    quote (e.g. a CLAD-definition sentence cannot justify a baseline-FEV1-method score).
  - If you cannot find an item-specific verbatim quote, the score is 0.
  - For score 0 and "NA", evidence_quote MUST be empty ("").
  - Quote verbatim; minimal span that proves the point.

READING TABLES (critical — do NOT under-read baseline data):
  - Much of the cohort/case-mix data lives in a "Baseline characteristics" / Table 1 and in the Methods, NOT
    the prose. Before scoring any descriptor 0, CHECK THE TABLES: indication/diagnosis mix, single vs bilateral
    procedure, transplant era/dates, number of centers, race/ethnicity, sample size, and follow-up are almost
    always tabulated even when the text does not restate them.
  - A value in a table IS valid evidence — quote the table cell/row verbatim (e.g. "COPD 41 (30%)",
    "Bilateral 88 (62%)", "2010–2018", "median follow-up 3.2 y (IQR 1.8–5.1)"). Set location to the table.
  - Score 0 ONLY when the item is genuinely absent from BOTH the tables and the text — never merely because it
    is not in the prose. A mention that meets partial(1) scores at least 1; do not default it to 0."""

_ADJUSTMENT = """ADJUSTMENT (per item — grounded; MULTIVARIABLE only; evidence-required):
  For each item report adjusted_model, adjusted, adjusted_evidence:
  - adjusted_model = "multivariable"    : THIS covariate is entered in a MULTIVARIABLE model for CLAD
                                          (multiple covariates fitted jointly: multivariable Cox / logistic /
                                          competing-risks, or an "adjusted HR/OR" column of a two-column table).
                     "univariable_only" : THIS covariate appears ONLY in a univariable/unadjusted analysis
                                          (a single-covariate HR/OR, or the unadjusted column of a table).
                     "none"             : not in any regression model (reported only in text/baseline table,
                                          or not at all).
  - CRITICAL: a table that lists a separate HR for each variable ONE AT A TIME is a series of UNIVARIABLE
    models — that is "univariable_only", NOT multivariable. Only mark "multivariable" if MULTIPLE covariates
    are fitted TOGETHER in one model. If a table has both an unadjusted and an "adjusted"/"multivariable"
    column, use the ADJUSTED column. If you cannot tell, use "univariable_only".
  - adjusted = true ONLY when adjusted_model == "multivariable".
  - adjusted = true REQUIRES adjusted_evidence: a verbatim phrase that BY ITSELF proves multivariable entry of
    THIS covariate — the covariate named in a multivariable-model sentence ("multivariable Cox … adjusted for
    …<covariate>…") or its row in an explicitly-adjusted/multivariable column. A bare variable name, a baseline
    value, a disease grade, or a univariable HR does NOT qualify.
  - adjusted = true is IMPOSSIBLE when score = 0. Do NOT mark a covariate adjusted because it is a plausible
    CLAD risk factor — only if the paper actually fits it in a multivariable model."""

_GROUNDING = """GROUNDING for analysis/methods flags (same evidence bar as items — do NOT infer from priors):
  - exposure_effect.significant = true/false ONLY if significance_evidence quotes the numeric result (an HR/OR
    with CI or a p-value) OR an explicit statement ("was/was not significantly associated"). If you cannot quote
    it, significant = null and significance_evidence = "". Do NOT infer significance from the effect direction.
  - time_varying_covariates / multiplicity_addressed / missing_data_handled = "yes" ONLY with a verbatim
    *_evidence quote proving the method was used (e.g. "modeled as a time-dependent covariate", "Bonferroni-
    corrected", "multiple imputation"). Without such a quote use "no" or "unclear" — never assert "yes" because
    it is good practice."""

_ITEM_SHAPE = ('{{ "<item_key>": {{"score": 2, "location": "Table 1 / Methods / Results", '
               '"value": "extracted value or \'\'", "evidence_quote": "verbatim from paper", '
               '"adjusted_model": "multivariable|univariable_only|none", '
               '"adjusted": false, "adjusted_evidence": "verbatim multivariable-model phrase or \'\'"}} }}')


def build_prompt_profile(text: str) -> str:
    """Call A — study/analysis profile + case-mix (A) + ascertainment (E) items."""
    keys = ", ".join(i.key for i in ITEMS if i.tier in "AE")
    panel_keys = ", ".join(i.key for i in ITEMS)  # full vocab for adjustment_set
    return f"""Profile this lung-transplant study and score the CASE-MIX and OUTCOME-ASCERTAINMENT items only.

{_SCORING}

{_ADJUSTMENT}

{_GROUNDING}

OUTCOME ROLE — how CLAD functions in THIS study:
  primary    = CLAD (or BOS/RAS) is a pre-specified primary endpoint, powers the sample size, or is the
               outcome of the headline analysis (e.g. CLAD-free survival as the main Cox/KM outcome).
  secondary  = analyzed as an outcome but explicitly secondary / one of several.
  descriptor = appears only as a baseline/cohort figure, no exposure→CLAD analysis.
  exclude    = CLAD only in intro/discussion; the study is about something else.
  If ambiguous between primary and secondary, choose secondary.

STUDY-LEVEL & ANALYSIS FIELDS (read from Methods/Results; do NOT guess — use 'unclear'/null):
  - study_design: classify by these rules, preferring the paper's OWN stated design verbatim —
      rct                  = randomized treatment allocation
      registry             = analysis of a NAMED organ registry (UNOS / OPTN / SRTR / ISHLT / UK Transplant /
                             Eurotransplant / national database) — choose this EVEN IF called retrospective
      prospective_cohort   = subjects enrolled and data collected FORWARD per protocol, or states "prospective"
      retrospective_cohort = existing records/charts reviewed after the fact ("retrospective review/analysis")
      cross_sectional | other
  - study_design_evidence: the verbatim phrase that justifies the design label ("" if truly none — then use 'other')
  - sample_size: integer lung-transplant recipients analyzed (null if unclear)
  - followup: median follow-up as reported, verbatim string ("" if none)
  - adjustment_set: ARRAY of item_keys from this vocabulary [{panel_keys}] entered as covariates in the
      PRIMARY multivariable model FOR CLAD. MUST equal exactly the keys you mark adjusted=true in items
      (same evidence bar — see ADJUSTMENT). [] if univariable-only / descriptive / no CLAD model.
  - primary_exposure: main exposure analyzed against CLAD ("" if purely descriptive)
  - exposure_effect: {{"measure":"HR|OR|other|","estimate":"","ci":"","significant":true|false|null,
               "significance_evidence":"verbatim HR/OR+CI/p or significance statement, else ''"}}
  - analysis: {{"survival_method":"none|km_logrank|cox_ph|competing_risk|logistic|other",
               "time_varying_covariates":"yes|no|unclear", "time_varying_covariates_evidence":"",
               "multiplicity_addressed":"yes|no|na|unclear", "multiplicity_addressed_evidence":"",
               "n_clad_events": integer or null, "n_covariates_in_model": integer or null}}
  - funding: industry | public_nonprofit | mixed | none_stated | unclear
  - missing_data_handled: yes | no | unclear
  - missing_data_handled_evidence: verbatim quote for a "yes"/"no", else ""
  - strobe_cited: true | false
  INTERVENTION / TRIAL (the "where are the CLAD trials?" landscape):
  - is_interventional: true | false — DESIGN flag ONLY: does the study TEST a therapy/procedure/protocol
      change under an ASSIGNED intervention (a trial), vs pure observation? A prospective/retrospective
      cohort with no assigned intervention is false. (Do NOT use this to gate intervention_intent below.)
  - intervention: the therapy/procedure/protocol evaluated (e.g. azithromycin, montelukast, extracorporeal
      photopheresis, total lymphoid irradiation, mTOR-inhibitor switch, antifibrotic, aerosolized ciclosporin),
      whether ASSIGNED (a trial) OR compared OBSERVATIONALLY; "" only if the exposure is not a therapy at all.
  - intervention_intent: prevent_clad | treat_clad | na — classify WHENEVER the exposure is a therapy/
      procedure/protocol, INCLUDING observational comparisons, INDEPENDENT of is_interventional. Judge by the
      ENROLLED population: prevent_clad = enrols patients WITHOUT established CLAD, to stop it developing — this
      INCLUDES interventions that modify an upstream CLAD risk factor (e.g. GERD, CMV, DSA) in patients without
      established CLAD; treat_clad = enrols patients who ALREADY have CLAD/BOS/RAS. na ONLY if the exposure is
      not a therapy or intent genuinely cannot be told. NB a drug given to patients who ALREADY have BOS but
      described as "preventing progression" is treat_clad — judge by whether the enrolled patients have CLAD.
  - trial_registered: yes | no | unclear
  - registration_id: NCT/EudraCT identifier or ""

SCORE THESE PANEL ITEMS (case-mix + ascertainment only; keys: {keys}):
{_codebook("AE")}

Return ONLY this JSON:
{{
  "outcome_role": "primary|secondary|descriptor|exclude",
  "outcome_role_reason": "one sentence",
  "study_design": "retrospective_cohort",
  "study_design_evidence": "",
  "sample_size": null,
  "followup": "",
  "adjustment_set": [],
  "primary_exposure": "",
  "exposure_effect": {{"measure":"","estimate":"","ci":"","significant":null,"significance_evidence":""}},
  "analysis": {{"survival_method":"none","time_varying_covariates":"unclear","time_varying_covariates_evidence":"","multiplicity_addressed":"unclear","multiplicity_addressed_evidence":"","n_clad_events":null,"n_covariates_in_model":null}},
  "funding": "unclear",
  "missing_data_handled": "unclear",
  "missing_data_handled_evidence": "",
  "strobe_cited": false,
  "is_interventional": false,
  "intervention": "",
  "intervention_intent": "na",
  "trial_registered": "unclear",
  "registration_id": "",
  "items": {_ITEM_SHAPE},
  "notes": ""
}}

PAPER FULL TEXT:
\"\"\"
{text[:MAX_CHARS]}
\"\"\"
"""


def build_prompt_panel(text: str) -> str:
    """Call B — the clinical covariate panel: immunological (B), second-hits (C), emerging (D)."""
    keys = ", ".join(i.key for i in ITEMS if i.tier in "BCD")
    return f"""Score how completely this lung-transplant study REPORTS each covariate below (immunological,
non-alloimmune second hits, and emerging determinants).

{_SCORING}

{_ADJUSTMENT}

COVARIATE PANEL (keys: {keys}):
{_codebook("BCD")}

Return ONLY this JSON:
{{
  "items": {_ITEM_SHAPE},
  "notes": ""
}}

PAPER FULL TEXT:
\"\"\"
{text[:MAX_CHARS]}
\"\"\"
"""


def _jats_text(path) -> str:
    """Flatten JATS full text: title + abstract + body prose (drop refs/back matter)."""
    from lxml import etree

    tree = etree.parse(str(path))
    root = tree.getroot()
    for tag in ("ref-list", "back"):
        for el in root.iter(tag):
            el.getparent().remove(el) if el.getparent() is not None else None
    parts = []
    for xp in (".//front//article-title", ".//front//abstract", ".//body"):
        for node in root.findall(xp):
            parts.append(" ".join(node.itertext()))
    return "\n\n".join(t.strip() for t in parts if t.strip())


def paper_text(pmid: str) -> str:
    """Prefer clean JATS XML (Europe PMC) → plain text (ISTEX) → scraped PDF."""
    xml = FULLTEXT_DIR / f"{pmid}.xml"
    if xml.exists():
        return _jats_text(xml)
    txt = FULLTEXT_DIR / f"{pmid}.txt"
    if txt.exists():
        return txt.read_text(errors="ignore")
    pdf = FULLTEXT_DIR / f"{pmid}.pdf"
    if pdf.exists():
        with fitz.open(pdf) as doc:
            return "\n".join(page.get_text() for page in doc)
    raise FileNotFoundError(f"no full text for {pmid} (.xml/.txt/.pdf)")


def _json_from(text: str) -> dict:
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError(f"no JSON in response: {text[:200]}")
    return json.loads(text[s : e + 1])


def call_claude(prompt: str, model: str, key: str) -> dict:
    r = requests.post(
        ANTHROPIC_URL,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 8000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300,
    )
    r.raise_for_status()
    body = r.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    return _json_from(text)


def openai_request_body(prompt: str, model: str) -> dict:
    """The /v1/responses request body — shared by the sync call and the Batch JSONL."""
    return {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "low", "format": {"type": "json_object"}},
        "max_output_tokens": 8000,
    }


def openai_text(body: dict) -> str:
    """Pull the model's text out of a /v1/responses result body (sync or batch)."""
    text = body.get("output_text", "")
    if not text:
        parts = []
        for item in body.get("output", []):
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    parts.append(c["text"])
        text = "".join(parts)
    return text


def call_openai(prompt: str, model: str, key: str) -> dict:
    """GPT-5.6 family via the Responses API. effort/verbosity low; temperature unsupported (omitted)."""
    r = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json=openai_request_body(prompt, model),
        timeout=300,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return _json_from(openai_text(r.json()))


def load_design_meta() -> dict[str, str]:
    """pmid -> authoritative design hint (rct/registry/'') from corpus_routed.csv."""
    import pandas as pd

    routed = DATA_DIR / "corpus_routed.csv"
    if routed.exists():
        cdf = pd.read_csv(routed, dtype={"pmid": str})
        if "design_meta" in cdf.columns:
            return dict(zip(cdf["pmid"], cdf["design_meta"].fillna("")))
    return {}


def finalize(pmid: str, profile: dict, panel: dict, design_meta: dict[str, str]) -> dict:
    """Merge the two calls, compute Python-side scores, reconcile study_design. Shared by sync + batch."""
    result = dict(profile)
    result["items"] = _enforce_adjustment({**profile.get("items", {}), **panel.get("items", {})})
    _enforce_grounding(result)
    if panel.get("notes"):
        result["notes"] = f"{result.get('notes', '')} | panel: {panel['notes']}".strip(" |")
    items = result.get("items", {})
    result["pmid"] = pmid
    result["min_set_met"] = _min_set_met(items)   # completeness metrics (min-set count) are derived downstream
    a = result.get("analysis", {}) or {}
    ev, nc = a.get("n_clad_events"), a.get("n_covariates_in_model")
    result["events_per_variable"] = round(ev / nc, 1) if isinstance(ev, int) and isinstance(nc, int) and nc else None
    llm_design = result.get("study_design", "")
    meta = design_meta.get(pmid, "")
    result["study_design_llm"] = llm_design
    result["study_design_meta"] = meta
    # Authoritative metadata (from route.py: named-registry / RCT detection) overrides the LLM design.
    # Both rct AND registry win — the codebook says a named-registry analysis is "registry" even when the
    # paper calls itself retrospective, and the LLM frequently mislabels these (see design_disagreement).
    result["study_design"] = meta if meta in ("rct", "registry") else llm_design
    result["design_disagreement"] = bool(meta and meta != llm_design)
    result["_provenance"] = {
        "protocol": PROTOCOL_VERSION,
        "model": DEFAULT_MODELS["openai"],
        "n_panel_items": len(ITEMS),
        "extracted": datetime.date.today().isoformat(),
    }
    return result


def _enforce_adjustment(items: dict) -> dict:
    """Grounded-adjustment guardrail (deterministic, model-independent). `adjusted=true` survives ONLY with
    score>=1, a non-empty adjusted_evidence, and adjusted_model=='multivariable'. Anything else — a univariable
    HR, a baseline value, an empty/absent model type, or score 0 — is forced to adjusted=false. Prevents the
    univariable/bivariate-table cases from counting as adjustment."""
    for v in items.values():
        if not isinstance(v, dict):
            continue
        sc = v.get("score")
        ok = (isinstance(sc, int) and sc >= 1
              and str(v.get("adjusted_evidence", "")).strip() != ""
              and v.get("adjusted_model") == "multivariable")
        v["adjusted"] = bool(v.get("adjusted") in (True, "true") and ok)
    return items


def _enforce_grounding(result: dict) -> dict:
    """Deterministic guardrail for analysis/methods flags (mirrors _enforce_adjustment): a substantive value
    survives only with a verbatim evidence quote, else it falls back to the conservative null/unclear direction.
    Targets the ungrounded-inference fields — significance, time-varying covariates, multiplicity, missing data."""
    eff = result.get("exposure_effect") or {}
    if not str(eff.get("significance_evidence", "")).strip():
        eff["significant"] = None                          # no quoted estimate/p/statement -> unknown, not inferred
    result["exposure_effect"] = eff
    ana = result.get("analysis") or {}
    for f in ("time_varying_covariates", "multiplicity_addressed"):
        if ana.get(f) == "yes" and not str(ana.get(f + "_evidence", "")).strip():
            ana[f] = "unclear"                             # "method was used" needs proof; else unknown
    result["analysis"] = ana
    if result.get("missing_data_handled") == "yes" and not str(result.get("missing_data_handled_evidence", "")).strip():
        result["missing_data_handled"] = "unclear"
    return result


def _min_set_met(items: dict) -> bool:
    """Whether all minimum-set items (MIN_SET, six after induction dropped 2026-08-08) are reported in full
    (score == 2). build_frame recomputes this from MIN_SET too, so it stays correct without a re-extraction.
    The primary completeness metric is the min-set COUNT, derived in build_frame; the old 0-100
    interpretability composite is scrapped."""
    return all(items.get(k, {}).get("score") == 2 for k in MIN_SET)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pmids", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--provider", default=DEFAULT_PROVIDER, choices=["openai", "anthropic"])
    ap.add_argument("--model", default=None, help="defaults per provider")
    ap.add_argument("--dry-run", action="store_true", help="extract text only, no API call")
    ap.add_argument("--out-dir", default=None, help="output dir name under data/ (default data/extractions; use a test dir to avoid touching production)")
    args = ap.parse_args()
    model = args.model or DEFAULT_MODELS[args.provider]
    out_dir = (DATA_DIR / args.out_dir) if args.out_dir else EXTRACT_DIR

    load_dotenv(PROJECT_ROOT / ".env")
    saved = sorted(p.stem for p in FULLTEXT_DIR.glob("*.pdf"))
    if args.pmids:
        pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
    elif args.sample:
        # deterministic spread across the saved set (no RNG needed)
        step = max(1, len(saved) // args.sample)
        pmids = saved[::step][: args.sample]
    else:
        pmids = saved
    print(f"{len(saved)} PDFs on disk; extracting {len(pmids)}: {pmids}")

    if args.dry_run:
        for pmid in pmids:
            t = paper_text(pmid)
            print(f"  {pmid}: {len(t):>7} chars  | head: {t[:90].strip()!r}")
        return

    env_key = "OPENAI_API_KEY" if args.provider == "openai" else "ANTHROPIC_API_KEY"
    key = os.environ.get(env_key, "").strip()
    if not key:
        sys.exit(f"{env_key} missing from .env — add it to run the extraction.")
    caller = call_openai if args.provider == "openai" else call_claude
    print(f"provider={args.provider} model={model} -> {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    design_meta = load_design_meta()

    for pmid in pmids:
        try:
            text = paper_text(pmid)
            profile = caller(build_prompt_profile(text), model, key)   # Call A: profile + A/E items
            panel = caller(build_prompt_panel(text), model, key)       # Call B: B/C/D covariate panel
        except Exception as e:  # noqa: BLE001
            print(f"  {pmid}: FAILED — {e}")
            continue
        result = finalize(pmid, profile, panel, design_meta)
        items = result["items"]
        (out_dir / f"{pmid}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        role = result.get("outcome_role", "?")
        nfull = sum(1 for v in items.values() if v.get("score") == 2)
        des = result.get("study_design", "?")
        a = result.get("analysis", {}) or {}
        surv = a.get("survival_method", "?")
        tvc = a.get("time_varying_covariates", "?")
        print(f"  {pmid}: role={role:<10} design={des:<22} full={nfull:>2}/{len(items)} "
              f"min_set_met={result['min_set_met']} surv={surv} tvc={tvc}")

    print(f"\nsaved to {out_dir}")   # not EXTRACT_DIR: --out-dir runs would misreport the target


if __name__ == "__main__":
    main()
