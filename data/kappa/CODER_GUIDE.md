# Coder guide — CLAD reporting-audit validation

You are checking, blinded, what a language model extracted from 90 lung-transplant papers. Two coders
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
SCORING (per item):
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
    is not in the prose. A mention that meets partial(1) scores at least 1; do not default it to 0.
```

### Per-item anchors
| Item | Score 2 = full | Score 1 = partial | Applies when (else `na`) |
|---|---|---|---|
| CMV D/R serostatus ★ | D/R matrix or D+/R−,R+,D−/R− ns | recipient-only / 'high-risk n' | always applicable |
| HLA mismatch ★ | mismatch reported by locus (≥ A, B, DR); DQ/DP or eplet/molecular detail credited but not required. NB: recipient sensitization (cPRA/PRA) is NOT mismatch — it belongs to pre_tx_dsa | overall/total antigen-mismatch count only (e.g. mean n/6), or a qualitative HLA-matching statement | always applicable |
| Maintenance IS ★ | CNI type + antimetabolite + steroid ±mTOR, n/% (dosing NOT required) | 'standard triple therapy' | always applicable |
| ACR burden ★ | A-grade distribution or ≥A1/A2 rate/freq | 'treated for rejection' | always applicable |
| AMR ★ | defined + incidence (pAMR/criteria) | mentioned as possible | always applicable |

## papers tab — structural characteristics (one row per paper)
**Outcome role** (`human_outcome_role`):
- **primary** — CLAD (or a named phenotype BOS/RAS) is a pre-specified primary endpoint — named in the objective/hypothesis, powers the sample size, or is the outcome of the headline analysis (e.g. the main time-to-CLAD / CLAD-free survival or Cox model).
- **secondary** — CLAD is analysed as an outcome (a comparison, model, or incidence by group) but is explicitly secondary, or one of several endpoints with no single headline. If primary-vs-secondary is ambiguous, choose secondary (the conservative call).
- **descriptor** — CLAD appears only as a baseline/cohort figure or a count in passing — NO analysis relating any exposure to it.
- **exclude** — CLAD is mentioned only in the intro/discussion; the study is really about something else.

**Study design** (`human_study_design`): one of `rct` / `prospective_cohort` / `retrospective_cohort` / `registry` / `cross_sectional` / `other`.

## intent tab — intervention_intent (40 interventional papers)
- **prevent_clad** — The intervention aims to PREVENT CLAD — it enrols patients who do NOT yet have established CLAD and tries to stop it developing. This INCLUDES interventions that modify an upstream CLAD risk factor (e.g. GERD, CMV, DSA) in patients without established CLAD.
- **treat_clad** — The intervention aims to TREAT patients who ALREADY have established CLAD/BOS/RAS at enrolment.
- **na** — Neither — the exposure is not a therapy (e.g. a transplant-type / donor / allocation comparison), or intent can't be told. Watch out: a drug given to patients who already have BOS but described as 'preventing progression' is treat_clad — judge by whether the ENROLLED patients already have CLAD.

## When you're done
Save the workbook. When BOTH coders are finished, the analyst runs `Rscript analysis/08_kappa.R` — it rejects any
value outside the lists above, so a typo surfaces immediately.
