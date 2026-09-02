# Kappa coding — instructions

**Start with [`CODER_GUIDE.md`](CODER_GUIDE.md)** (the full rubric — also the first *guide* tab inside your workbook). Each coder gets **one workbook — `coder_<A|B>.xlsx`** — with four tabs:
- **guide** — the scoring rubric + per-item anchors + role/design/intent definitions.
- **items** — the 6 ★ minimum-set items (the primary judgment criterion) on all 90 papers; ~450 rows.
- **papers** — outcome role + study design, one row per paper.
- **intent** — intervention_intent for the 40 interventional papers.

Two coders (A, B) score INDEPENDENTLY and blinded.

## Reading the paper
Open the **`read_paper`** link — the published article (DOI, else PubMed). Read *that*, via your institutional access. `source_file` is only the machine copy the LLM saw (JATS-XML or PDF); reference only — do not try to read the raw XML.

## Scoring
1. Work **paper by paper, top to bottom** on the *items* tab; within each paper the ★ rows come first.
2. Fill the graded columns from the **dropdown**. Excel and LibreOffice show it; **Apple Numbers usually does not import the dropdown** — if you use Numbers, type the value exactly (lists below). Use the `full_2` / `partial_1` anchors in each row.
3. Do NOT open the `kappa_key*.csv` files (the LLM answers). When both coders are done, run `Rscript analysis/08_kappa.R` — it rejects any out-of-list value, so typos surface immediately.

## Valid values
- `human_score`: **not / partial / full / na**  (na = the conditional item's trigger population is absent — see `conditional_trigger`)
- `human_outcome_role`: **primary / secondary / descriptor / exclude**
- `human_study_design`: **rct / prospective_cohort / retrospective_cohort / registry / cross_sectional / other**
- `human_intent`: **prevent_clad / treat_clad / na**

**Focus check:** HLA / CMV items scored `not` on a PDF source — verify carefully (table-extraction risk).
