"""Kappa validation — blinded export.

Draws a stratified random subset of analyzable papers (outcome_role × era × source_format) and writes
BLINDED coding sheets (one per coder) plus a hidden key with the LLM scores. Human coders read the full
text and score each item (not/partial/full/na) WITHOUT seeing the LLM's answers; the scoring step
(analysis/08_kappa.R) then computes weighted-κ (LLM vs human, and human vs human).

Tiered by design (see docs/validation-plan.md) so coder effort lands on the headline:
  * the 6 MINIMUM-SET items are scored on all --n papers (the load-bearing κ);
  * the full 37-item panel is scored only on a nested --full-n subsample (panel-wide κ);
  * intervention_intent (prevent_clad vs treat_clad) — the REPORTED full-text intent — on ~--intent-n papers.

    uv run python -m clad_audit.kappa_export                 # tiered default (n=90, full-n=40, intent-n=40)
    uv run python -m clad_audit.kappa_export --items minset  # fast primary pass: min-set on all --n only

Outputs → data/kappa/ (gitignored):
  coding_sheet_<A|B>.csv       blinded item-level sheet per coder (fill `human_score`); ★ min-set rows first
  paper_sheet_<A|B>.csv        per-paper outcome_role / study_design coding
  trials_intent_sheet_<A|B>.csv  per-interventional-paper intervention_intent coding
  kappa_key.csv                HIDDEN — LLM item scores (do NOT show coders)
  kappa_key_paper.csv          HIDDEN — LLM outcome_role / study_design
  kappa_key_intent.csv         HIDDEN — LLM intervention_intent
  sample_manifest.csv          the sampled pmids + strata
  README.md                    coding instructions + valid values
"""

from __future__ import annotations

import argparse
import random
import shutil
from collections import defaultdict
from datetime import datetime

import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .config import CORPUS_CSV, DATA_DIR
from .extract import _SCORING          # the exact scoring rubric shown to the model — reused so the guide can't drift
from .panel import ITEMS

# allowed values per graded column → dropdown lists (and the intake re-checks them)
SCORE_VALS = ["not", "partial", "full", "na"]
ROLE_VALS = ["primary", "secondary", "descriptor", "exclude"]
DESIGN_VALS = ["rct", "prospective_cohort", "retrospective_cohort", "registry", "cross_sectional", "other"]
INTENT_VALS = ["prevent_clad", "treat_clad", "na"]

# plain-language definitions for the structural axes (papers + intent tabs), mirroring scoring-codebook.md §2
# and classify.py. Kept here so they render into the coder guide the coders actually read.
ROLE_DEFS = [
    ("primary", "CLAD (or a named phenotype BOS/RAS) is a pre-specified primary endpoint — named in the "
                "objective/hypothesis, powers the sample size, or is the outcome of the headline analysis "
                "(e.g. the main time-to-CLAD / CLAD-free survival or Cox model)."),
    ("secondary", "CLAD is analysed as an outcome (a comparison, model, or incidence by group) but is explicitly "
                  "secondary, or one of several endpoints with no single headline. If primary-vs-secondary is "
                  "ambiguous, choose secondary (the conservative call)."),
    ("descriptor", "CLAD appears only as a baseline/cohort figure or a count in passing — NO analysis relating "
                   "any exposure to it."),
    ("exclude", "CLAD is mentioned only in the intro/discussion; the study is really about something else."),
]
INTENT_DEFS = [
    ("prevent_clad", "The intervention aims to PREVENT CLAD — it enrols patients who do NOT yet have established "
                     "CLAD and tries to stop it developing. This INCLUDES interventions that modify an upstream "
                     "CLAD risk factor (e.g. GERD, CMV, DSA) in patients without established CLAD."),
    ("treat_clad", "The intervention aims to TREAT patients who ALREADY have established CLAD/BOS/RAS at enrolment."),
    ("na", "Neither — the exposure is not a therapy (e.g. a transplant-type / donor / allocation comparison), or "
           "intent can't be told. Watch out: a drug given to patients who already have BOS but described as "
           "'preventing progression' is treat_clad — judge by whether the ENROLLED patients already have CLAD."),
]

FRAME = DATA_DIR / "analysis_frame.csv"
KDIR = DATA_DIR / "kappa"
SEED = 20260805  # fixed for reproducibility (regular Python RNG; deterministic given the frame)
WB_TS = datetime(2026, 8, 5)  # fixed workbook timestamp → coder_A/B.xlsx are byte-identical and re-runs reproducible

# minimum-set items first, original panel order preserved within each group (stable sort). ★ on the min-set.
ITEMS_ORDERED = sorted(ITEMS, key=lambda it: (not it.min_set,))


def _stratified_sample(an: pd.DataFrame, n: int, seed: int = SEED) -> list[str]:
    """Return n pmids drawn proportionally across outcome_role × era × source_format strata."""
    strata: dict = defaultdict(list)
    for _, r in an.iterrows():
        strata[(r["outcome_role"], r["era"], r["source_format"])].append(r["pmid"])
    rng = random.Random(seed)
    total = len(an)
    picked: list[str] = []
    for key, pmids in sorted(strata.items(), key=lambda kv: str(kv[0])):
        rng.shuffle(pmids)
        k = max(1, round(n * len(pmids) / total))
        picked.extend(pmids[:k])
    rng.shuffle(picked)
    return picked[:n]


def _dropdown(ws, df: pd.DataFrame, colname: str, values: list[str]) -> None:
    """Attach an Excel list-validation dropdown to a graded column (Excel/LibreOffice honour it)."""
    if colname not in df.columns:
        return
    col = get_column_letter(list(df.columns).index(colname) + 1)
    dv = DataValidation(type="list", formula1='"%s"' % ",".join(values), allow_blank=True, showErrorMessage=True)
    dv.errorTitle, dv.error = "Invalid entry", "Use one of: " + ", ".join(values)
    ws.add_data_validation(dv)
    dv.add(f"{col}2:{col}{len(df) + 1}")


def _write_guide_sheet(ws, items) -> None:
    """A first 'guide' tab so the rubric travels inside the workbook (the coder opens one file)."""
    from openpyxl.styles import Alignment, Font
    big, bold = Font(bold=True, size=14), Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    r = 1

    def row(text: str = "", font=None):
        nonlocal r
        c = ws.cell(row=r, column=1, value=text)
        c.alignment = wrap
        if font:
            c.font = font
        r += 1

    row("Coder guide — CLAD reporting-audit validation", big)
    row("Full written version: CODER_GUIDE.md (open alongside). Read each paper via its read_paper link.")
    row()
    row("HOW TO SCORE — items tab", bold)
    for ln in _SCORING.splitlines():
        row(ln)
    row()
    row("PER-ITEM ANCHORS  (identical to the full_2 / partial_1 columns already in the items tab)", bold)
    for j, h in enumerate(["Item", "Score 2 = full", "Score 1 = partial", "Applies when (else 'na')"], 1):
        c = ws.cell(row=r, column=j, value=h)
        c.font, c.alignment = bold, wrap
    r += 1
    for it in items:
        cells = [f"{it.label} ★" if it.min_set else it.label, it.full, it.partial, it.trigger or "always applicable"]
        for j, v in enumerate(cells, 1):
            ws.cell(row=r, column=j, value=v).alignment = wrap
        r += 1
    row()
    row("PAPERS tab — outcome role (one per paper)", bold)
    for k, v in ROLE_DEFS:
        row(f"  {k} — {v}")
    row()
    row("PAPERS tab — study design", bold)
    row("  choose one: " + " / ".join(DESIGN_VALS))
    row()
    row("INTENT tab — intervention_intent (interventional papers only)", bold)
    for k, v in INTENT_DEFS:
        row(f"  {k} — {v}")
    ws.column_dimensions["A"].width = 46
    for col in ("B", "C"):
        ws.column_dimensions[col].width = 50
    ws.column_dimensions["D"].width = 28


def _guide_md(sample_n: int, items, intent_n: int) -> str:
    anchors = ["| Item | Score 2 = full | Score 1 = partial | Applies when (else `na`) |", "|---|---|---|---|"]
    for it in items:
        lbl = f"{it.label} ★" if it.min_set else it.label
        anchors.append(f"| {lbl} | {it.full} | {it.partial} | {it.trigger or 'always applicable'} |")
    role = "\n".join(f"- **{k}** — {v}" for k, v in ROLE_DEFS)
    intent = "\n".join(f"- **{k}** — {v}" for k, v in INTENT_DEFS)
    design = " / ".join(f"`{d}`" for d in DESIGN_VALS)
    return f"""# Coder guide — CLAD reporting-audit validation

You are checking, blinded, what a language model extracted from {sample_n} lung-transplant papers. Two coders
(A, B) work **independently**. Everything is in your workbook **`coder_<A|B>.xlsx`** (tabs: **guide**, **items**,
**papers**, **intent**); this file is the same content, to read or print.

## Read the actual paper
Open each row's **`read_paper`** link — the published article (DOI, else PubMed) — and read *that*, via your
institutional access. `source_file` is only the machine copy the model saw (JATS-XML or PDF); a reference, never
your reading source. Do **not** open the `kappa_key*.csv` files (the model's answers).

## items tab — how to score
Each row is one item in one paper. Put **not / partial / full / na** in `human_score`, using the anchors in the
`full_2` / `partial_1` columns (reproduced below). The exact rubric the model was given:

```
{_SCORING}
```

### Per-item anchors
{chr(10).join(anchors)}

## papers tab — structural characteristics (one row per paper)
**Outcome role** (`human_outcome_role`):
{role}

**Study design** (`human_study_design`): one of {design}.

## intent tab — intervention_intent ({intent_n} interventional papers)
{intent}

## When you're done
Save the workbook. When BOTH coders are finished, the analyst runs `Rscript analysis/08_kappa.R` — it rejects any
value outside the lists above, so a typo surfaces immediately.
"""


def _write_coder_workbook(path, items_df: pd.DataFrame, paper_df: pd.DataFrame, intent_df: pd.DataFrame,
                          guide_items) -> None:
    """One workbook per coder: guide / items / papers / intent tabs, dropdown-validated graded columns."""
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        items_df.to_excel(xw, sheet_name="items", index=False)
        paper_df.to_excel(xw, sheet_name="papers", index=False)
        intent_df.to_excel(xw, sheet_name="intent", index=False)
        _dropdown(xw.sheets["items"], items_df, "human_score", SCORE_VALS)
        _dropdown(xw.sheets["papers"], paper_df, "human_outcome_role", ROLE_VALS)
        _dropdown(xw.sheets["papers"], paper_df, "human_study_design", DESIGN_VALS)
        _dropdown(xw.sheets["intent"], intent_df, "human_intent", INTENT_VALS)
        for name in ("items", "papers", "intent"):
            xw.sheets[name].freeze_panes = "A2"
        _write_guide_sheet(xw.book.create_sheet("guide", 0), guide_items)   # guide first
        xw.book.properties.created = xw.book.properties.modified = WB_TS     # deterministic: A == B, stable re-runs


def _read_url(pmid: str, doi) -> str:
    """Where a HUMAN reads the paper: the published article via DOI, else the PubMed record."""
    doi = str(doi).strip() if doi is not None else ""
    if doi in ("", "nan"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return f"https://doi.org/{doi}"


def _item_rows(sample: pd.DataFrame, full_pmids: set[str], titles: dict, dois: dict, minset_only: bool) -> list[dict]:
    """One row per (paper, item) the coder must score. Min-set on every paper; full panel only on full_pmids."""
    rows = []
    for _, r in sample.iterrows():
        full_scope = r["pmid"] in full_pmids and not minset_only
        for it in ITEMS_ORDERED:
            if not it.min_set and not full_scope:
                continue  # non-min-set item skipped on min-set-only papers
            rows.append({
                "pmid": r["pmid"],
                "title": (titles.get(r["pmid"], "") or "")[:120],
                "read_paper": _read_url(r["pmid"], dois.get(r["pmid"], "")),   # HUMAN reads this (published article)
                "source_file": f"data/fulltext/{r['pmid']}.{r['source_format']}",  # machine copy the LLM saw (ref only)
                "priority": 1 if it.min_set else 2,             # do priority-1 (★ min-set) rows first
                "scope": "minset" if it.min_set else "full",
                "tier": it.tier,
                "item_key": it.key,
                "item_label": f"{it.label} ★" if it.min_set else it.label,
                "full_2": it.full,
                "partial_1": it.partial,
                "conditional_trigger": it.trigger,
                "human_score": "",        # coder fills: not / partial / full / na
                "human_note": "",
            })
    # group by paper (read a paper once), min-set rows first within each paper
    rows.sort(key=lambda d: (list(sample["pmid"]).index(d["pmid"]), d["priority"]))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=90, help="papers scored on the minimum set (primary κ)")
    ap.add_argument("--full-n", type=int, default=40, help="[--items all only] nested subsample scored on the full 37-item panel")
    ap.add_argument("--intent-n", type=int, default=40, help="interventional papers scored for intervention_intent")
    ap.add_argument("--items", choices=["all", "minset"], default="minset",
                    help="default 'minset' = the 6 min-set items on every paper (the primary judgment criterion); "
                         "'all' additionally scores the full 37-item panel on --full-n papers")
    ap.add_argument("--coders", type=int, default=2)
    args = ap.parse_args()

    af = pd.read_csv(FRAME, dtype={"pmid": str})
    # Restrict to the ANALYZABLE cohort — the papers the headline reports on — so κ validates exactly those.
    # Mirrors analysis/00_setup.R: primary/secondary outcome, human/clinical, structure-based eligibility
    # (drop reviews/methods/case + mechanistic snapshots without an exposure→CLAD estimate).
    elig0 = af[af["outcome_role"].isin(["primary", "secondary"])].copy()
    elig0 = elig0[~elig0["clinical"].astype(str).isin(["False", "FALSE", "false"])]
    has_exp = elig0["exposure_measure"].fillna("").astype(str).str.strip().ne("")
    an = elig0[
        ~elig0["study_type"].isin(["methods_or_review", "case_report_series"])
        & ~((elig0["study_type"] == "mechanistic_translational") & ~has_exp)
    ].copy()
    meta = pd.read_csv(CORPUS_CSV, dtype={"pmid": str}).set_index("pmid")
    titles = meta["title"].to_dict()
    dois = meta["doi"].fillna("").astype(str).to_dict() if "doi" in meta.columns else {}

    picked = _stratified_sample(an, args.n)
    sample = an[an["pmid"].isin(picked)].copy()
    sample["pmid"] = pd.Categorical(sample["pmid"], categories=picked, ordered=True)
    sample = sample.sort_values("pmid")
    sample["pmid"] = sample["pmid"].astype(str)
    full_pmids = set(picked[: args.full_n]) if args.items == "all" else set()

    KDIR.mkdir(parents=True, exist_ok=True)
    print(f"sampled {len(sample)} of {len(an)} analyzable, stratified by outcome_role × era × source_format")
    print(sample.groupby(["outcome_role", "era", "source_format"]).size().to_string())

    # ---- blinded item-level coding sheet (long) ----
    sheet = pd.DataFrame(_item_rows(sample, full_pmids, titles, dois, args.items == "minset"))
    # Drop helper columns that carry no information in this run, to declutter the coder's view: in the min-set-only
    # default `priority` is always 1, `scope` always "minset", and `conditional_trigger` empty (no conditional items).
    if sheet["conditional_trigger"].astype(str).str.strip().eq("").all():
        sheet = sheet.drop(columns="conditional_trigger")
    for col in ("priority", "scope"):
        if col in sheet.columns and sheet[col].nunique() <= 1:
            sheet = sheet.drop(columns=col)

    # ---- per-paper role/design sheet ----
    paper = pd.DataFrame({
        "pmid": sample["pmid"],
        "title": [(titles.get(p, "") or "")[:120] for p in sample["pmid"]],
        "read_paper": [_read_url(p, dois.get(p, "")) for p in sample["pmid"]],
        "source_file": [f"data/fulltext/{p}.{s}" for p, s in zip(sample["pmid"], sample["source_format"])],
        "human_outcome_role": "",   # primary / secondary / descriptor / exclude
        "human_study_design": "",   # rct / prospective_cohort / retrospective_cohort / registry / cross_sectional / other
    })

    # ---- interventional intent sheet (validates the REPORTED intent = full-text intervention_intent) ----
    intr = an[an.get("intervention_intent").isin(["prevent_clad", "treat_clad"])].copy()
    intent_pmids = _stratified_sample(intr, args.intent_n, seed=SEED + 1) if len(intr) else []
    intent = an[an["pmid"].isin(intent_pmids)].copy()
    intent_sheet = pd.DataFrame({
        "pmid": intent["pmid"],
        "title": [(titles.get(p, "") or "")[:120] for p in intent["pmid"]],
        "read_paper": [_read_url(p, dois.get(p, "")) for p in intent["pmid"]],
        "source_file": [f"data/fulltext/{p}.{s}" for p, s in zip(intent["pmid"], intent["source_format"])],
        "human_intent": "",         # prevent_clad / treat_clad / na
        "human_note": "",
    })

    for pat in ("coding_sheet_*.csv", "paper_sheet_*.csv", "trials_intent_sheet_*.csv"):
        for stale in KDIR.glob(pat):     # remove legacy per-coder CSVs so coders can't fill the wrong file
            stale.unlink()
    guide_items = [it for it in ITEMS_ORDERED if it.min_set or args.items == "all"]  # the items the coder scores
    coders = [chr(ord("A") + i) for i in range(args.coders)]
    first = KDIR / f"coder_{coders[0]}.xlsx"
    _write_coder_workbook(first, sheet, paper, intent_sheet, guide_items)
    for c in coders[1:]:                      # byte-copy so every coder starts from an identical blank workbook
        shutil.copyfile(first, KDIR / f"coder_{c}.xlsx")
    (KDIR / "CODER_GUIDE.md").write_text(_guide_md(len(sample), guide_items, len(intent_sheet)))

    # ---- HIDDEN keys (LLM answers) — never shown to coders ----
    key_rows = [
        {"pmid": r["pmid"], "item_key": it.key, "llm_score": r[f"score_{it.key}"]}
        for _, r in sample.iterrows()
        for it in ITEMS_ORDERED
        if it.min_set or (r["pmid"] in full_pmids and args.items == "all")
    ]
    pd.DataFrame(key_rows).to_csv(KDIR / "kappa_key.csv", index=False)
    sample[["pmid", "outcome_role", "study_design"]].rename(
        columns={"outcome_role": "outcome_role_llm", "study_design": "study_design_llm"}
    ).to_csv(KDIR / "kappa_key_paper.csv", index=False)
    intent[["pmid", "intervention_intent"]].rename(columns={"intervention_intent": "intervention_intent_llm"}).to_csv(
        KDIR / "kappa_key_intent.csv", index=False)
    sample[["pmid", "outcome_role", "era", "source_format"]].to_csv(KDIR / "sample_manifest.csv", index=False)

    n_full = len(full_pmids)
    per_coder = len(sheet)
    panel_note = f" (plus the full 37-item panel on {n_full} of them, `scope = full`)" if n_full else ""
    (KDIR / "README.md").write_text(
        "# Kappa coding — instructions\n\n"
        "**Start with [`CODER_GUIDE.md`](CODER_GUIDE.md)** (the full rubric — also the first *guide* tab inside your "
        "workbook). Each coder gets **one workbook — `coder_<A|B>.xlsx`** — with four tabs:\n"
        "- **guide** — the scoring rubric + per-item anchors + role/design/intent definitions.\n"
        f"- **items** — the 6 ★ minimum-set items (the primary judgment criterion) on all {len(sample)} papers"
        f"{panel_note}; ~{per_coder} rows.\n"
        "- **papers** — outcome role + study design, one row per paper.\n"
        f"- **intent** — intervention_intent for the {len(intent_sheet)} interventional papers.\n\n"
        "Two coders (A, B) score INDEPENDENTLY and blinded.\n\n"
        "## Reading the paper\n"
        "Open the **`read_paper`** link — the published article (DOI, else PubMed). Read *that*, via your "
        "institutional access. `source_file` is only the machine copy the LLM saw (JATS-XML or PDF); reference only — "
        "do not try to read the raw XML.\n\n"
        "## Scoring\n"
        "1. Work **paper by paper, top to bottom** on the *items* tab; within each paper the ★ rows come first.\n"
        "2. Fill the graded columns from the **dropdown**. Excel and LibreOffice show it; **Apple Numbers usually does "
        "not import the dropdown** — if you use Numbers, type the value exactly (lists below). Use the `full_2` / "
        "`partial_1` anchors in each row.\n"
        "3. Do NOT open the `kappa_key*.csv` files (the LLM answers). When both coders are done, run "
        "`Rscript analysis/08_kappa.R` — it rejects any out-of-list value, so typos surface immediately.\n\n"
        "## Valid values\n"
        "- `human_score`: **not / partial / full / na**  (na = the conditional item's trigger population is absent — "
        "see `conditional_trigger`)\n"
        "- `human_outcome_role`: **primary / secondary / descriptor / exclude**\n"
        "- `human_study_design`: **rct / prospective_cohort / retrospective_cohort / registry / cross_sectional / other**\n"
        "- `human_intent`: **prevent_clad / treat_clad / na**\n\n"
        "**Focus check:** HLA / CMV items scored `not` on a PDF source — verify carefully (table-extraction risk).\n"
    )

    hla_pdf_not = ((sample["source_format"] == "pdf") & (sample["score_hla_mismatch"] == "not")).sum()
    print(f"\nwrote coder sheets + hidden keys → {KDIR}")
    print(f"  item rows/coder: {per_coder} (min-set on {len(sample)} papers, full panel on {n_full}); "
          f"intent papers: {len(intent_sheet)}")
    print(f"  (table-check focus: {hla_pdf_not} sampled papers have HLA scored 'not' on a PDF source)")


if __name__ == "__main__":
    main()
