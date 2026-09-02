"""Kappa validation — blinded export for the TITLE/ABSTRACT CLASSIFIER (gate b).

The full-text extraction is validated by `kappa_export`. This is the other gate: `classify.py` reads
title+abstract and produces the fields that decide who is IN the audit at all —

  * study_type             gates eligibility (reviews/methods/case are dropped; a mechanistic study is
                           kept only if it carries an exposure->CLAD estimate), so it sets the denominator
  * evaluates_intervention authoritative for the interventional count and the trials-landscape figure
  * clinical               drops animal / in-vitro work
  * study_design           a comparator for the full-text pass (metadata wins for RCT/registry)

The coder reads the TITLE AND ABSTRACT ONLY — that is exactly what the classifier saw, so the comparison
is like-for-like and no full text is needed. Both are printed in the sheet, so the job needs no other file
open and runs far faster than the full-text pass.

    uv run python -m clad_audit.kappa_export_classifier            # 100 abstracts, boundary-weighted
    uv run python -m clad_audit.kappa_export_classifier --n 60     # smaller

Refuses to overwrite a sheet that already has coding in it (--force to override).

Outputs -> data/kappa/ (gitignored):
  classifier_sheet.xlsx        blinded coding sheet (fill the four human_* columns)
  kappa_key_classifier.csv     HIDDEN — the classifier's own labels (do NOT open before coding)
  classifier_manifest.csv      the sampled pmids + stratum
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime

import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .config import CORPUS_CSV, DATA_DIR

KDIR = DATA_DIR / "kappa"
CLASSIFICATIONS = DATA_DIR / "classifications.jsonl"
SEED = 20260814
WB_TS = datetime(2026, 8, 5)          # fixed so re-runs are byte-identical

TYPE_VALS = ["clinical_cohort", "mechanistic_translational", "registry", "trial",
             "methods_or_review", "case_report_series"]
YESNO = ["yes", "no"]
DESIGN_VALS = ["rct", "prospective_cohort", "retrospective_cohort", "registry", "cross_sectional", "other"]

# Boundary-weighted allocation. Sampling in proportion to the corpus would spend most of the budget on
# clinical_cohort, which is rarely the hard call. The eligibility gate turns on the clinical_cohort vs
# mechanistic_translational distinction, so those two strata are oversampled; the small strata get enough
# rows for their own κ to mean something rather than a proportional handful.
ALLOCATION = {"mechanistic_translational": 0.35, "clinical_cohort": 0.30, "methods_or_review": 0.12,
              "trial": 0.09, "registry": 0.08, "case_report_series": 0.06}


def _dropdown(ws, df: pd.DataFrame, colname: str, values: list[str]) -> None:
    if colname not in df.columns:
        return
    col = get_column_letter(list(df.columns).index(colname) + 1)
    dv = DataValidation(type="list", formula1='"%s"' % ",".join(values), allow_blank=True, showErrorMessage=True)
    dv.errorTitle, dv.error = "Invalid entry", "Use one of: " + ", ".join(values)
    ws.add_data_validation(dv)
    dv.add(f"{col}2:{col}{len(df) + 1}")


GUIDE = [
    ("Coder guide — title/abstract classifier validation", "head"),
    ("Score from the TITLE and ABSTRACT printed in each row. That is all the classifier saw; opening the "
     "full text would make the comparison unfair to it, and is not needed.", ""),
    ("", ""),
    ("study_type — what KIND of study is this? (sets who is in the audit)", "bold"),
    ("  clinical_cohort            patient-level clinical cohort (retrospective or prospective)", ""),
    ("  mechanistic_translational  biomarker / immunology / -omics work on patient samples", ""),
    ("  registry                   analysis of a named registry (UNOS, ISHLT, Eurotransplant...)", ""),
    ("  trial                      randomised or prospectively assigned interventional trial", ""),
    ("  methods_or_review          review, editorial, methods paper, guideline, consensus", ""),
    ("  case_report_series         case report or small descriptive series with no analysis", ""),
    ("  NB the clinical_cohort vs mechanistic_translational call is the one the eligibility gate turns on:", ""),
    ("  a mechanistic study stays in the audit ONLY if it estimates an exposure->CLAD effect.", ""),
    ("", ""),
    ("evaluates_intervention — does the study TEST a therapy, procedure, device, IS regimen,", "bold"),
    ("  prophylaxis or preservation strategy, as the subject of the study? yes / no.", ""),
    ("  A cohort that merely describes what patients received is 'no'.", ""),
    ("", ""),
    ("clinical — are the units of analysis human patients? yes / no (animal, in-vitro, pure lab = no).", "bold"),
    ("", ""),
    ("study_design — rct / prospective_cohort / retrospective_cohort / registry / cross_sectional / other.", "bold"),
    ("  Use 'other' when the abstract genuinely does not say. Do not infer from what is usual.", ""),
    ("", ""),
    ("Leave a row blank if the abstract is missing or unreadable. Notes column is free text.", ""),
]


def _write_guide(ws) -> None:
    from openpyxl.styles import Alignment, Font
    big, bold = Font(bold=True, size=14), Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    for i, (text, kind) in enumerate(GUIDE, start=1):
        c = ws.cell(row=i, column=1, value=text)
        c.alignment = wrap
        if kind == "head":
            c.font = big
        elif kind == "bold":
            c.font = bold
    ws.column_dimensions["A"].width = 118


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=100, help="abstracts to sample")
    ap.add_argument("--force", action="store_true", help="overwrite a sheet that already contains coding")
    a = ap.parse_args()

    KDIR.mkdir(parents=True, exist_ok=True)

    # Refuse to destroy work in progress. The sheet is written in place, so a second run — to change --n,
    # or simply not remembering the first — would silently wipe hours of coding with no undo.
    out_path = KDIR / "classifier_sheet.xlsx"
    if out_path.exists() and not a.force:
        try:
            existing = pd.read_excel(out_path, sheet_name="abstracts")
            coded = int(existing["human_study_type"].astype(str).str.strip().ne("").sum())
        except Exception:
            coded = 0
        if coded:
            raise SystemExit(
                f"{out_path} already has {coded} coded row(s). Re-exporting would overwrite them.\n"
                f"Move it aside first, or pass --force if you really mean to discard the coding.")
    cls = [json.loads(l) for l in CLASSIFICATIONS.open() if l.strip()]
    cls = [c for c in cls if c.get("study_type")]
    corpus = {r["pmid"]: r for r in csv.DictReader(CORPUS_CSV.open())}

    by_type: dict[str, list] = {}
    for c in cls:
        if c["pmid"] in corpus and (corpus[c["pmid"]].get("abstract") or "").strip():
            by_type.setdefault(c["study_type"], []).append(c)

    rng = random.Random(SEED)
    sample = []
    for st, share in ALLOCATION.items():
        pool = by_type.get(st, [])
        want = min(len(pool), round(a.n * share))
        sample += rng.sample(pool, want)
    rng.shuffle(sample)                      # strata interleaved, so the coder cannot infer the label from order

    rows, key = [], []
    for c in sample:
        rec = corpus[c["pmid"]]
        rows.append({"pmid": c["pmid"],
                     "title": rec.get("title", ""),
                     "abstract": rec.get("abstract", ""),
                     "read_paper": f"https://pubmed.ncbi.nlm.nih.gov/{c['pmid']}/",
                     "human_study_type": "", "human_evaluates_intervention": "",
                     "human_clinical": "", "human_study_design": "", "human_note": ""})
        key.append({"pmid": c["pmid"],
                    "study_type_llm": c.get("study_type"),
                    "evaluates_intervention_llm": "yes" if c.get("evaluates_intervention") else "no",
                    "clinical_llm": "yes" if c.get("clinical") else "no",
                    "study_design_llm": c.get("study_design")})

    df = pd.DataFrame(rows)
    out = out_path
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="abstracts", index=False)
        ws = xw.sheets["abstracts"]
        _dropdown(ws, df, "human_study_type", TYPE_VALS)
        _dropdown(ws, df, "human_evaluates_intervention", YESNO)
        _dropdown(ws, df, "human_clinical", YESNO)
        _dropdown(ws, df, "human_study_design", DESIGN_VALS)
        ws.freeze_panes = "A2"
        for col, w in (("A", 11), ("B", 60), ("C", 100), ("D", 34)):
            ws.column_dimensions[col].width = w
        from openpyxl.styles import Alignment
        for r in range(2, len(df) + 2):
            for col in ("B", "C"):
                ws[f"{col}{r}"].alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[r].height = 96
        _write_guide(xw.book.create_sheet("guide", 0))
        xw.book.properties.created = xw.book.properties.modified = WB_TS

    pd.DataFrame(key).to_csv(KDIR / "kappa_key_classifier.csv", index=False)
    pd.DataFrame([{"pmid": c["pmid"], "stratum": c["study_type"]} for c in sample]).to_csv(
        KDIR / "classifier_manifest.csv", index=False)

    counts = pd.Series([c["study_type"] for c in sample]).value_counts()
    print(f"wrote {out} ({len(df)} abstracts)")
    for k, v in counts.items():
        print(f"  {k:28s} {v}")
    print(f"hidden key -> {KDIR / 'kappa_key_classifier.csv'} (do not open before coding)")


if __name__ == "__main__":
    main()
