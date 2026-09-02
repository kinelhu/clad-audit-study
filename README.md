# CLAD reporting audit

Analysis code and derived data for a meta-research audit of how completely the lung-transplant chronic
lung allograft dysfunction (CLAD) literature reports and adjusts for the immunological determinants
needed to interpret a CLAD result.

This repository is the analysis. Manuscript sources are not included.

## Quickstart

```sh
Rscript -e 'renv::restore()'    # R 4.6.x, 144 locked packages
Rscript analysis/run_all.R      # writes analysis/tables/ and analysis/figures/
```

That is the whole reproduction path. It reads `data/analysis_frame.csv` and requires no API keys and
no network. It regenerates 5 main figures, 2 main tables, 17 supplementary tables, 3 supplementary
figures, and the validation statistics.

## Repository layout

| Path | Contents |
|---|---|
| `analysis/` | R analysis. One numbered script per exhibit family, orchestrated by `run_all.R` |
| `analysis/00_setup.R` | Cohort definition and eligibility gates. Sourced by every other script |
| `src/clad_audit/` | Python pipeline: discovery, retrieval, extraction. `panel.py` is the instrument |
| `data/` | Derived data. See [Data](#data) |
| `tools/` | Machine checks on the extraction: quote grounding and re-scoring stability |

Scripts locate the repository root by walking up to `renv.lock`, so they run from any directory.

## Data

| File | Contents |
|---|---|
| `analysis_frame.csv` | 1,653 studies x 136 columns: per-item scores (`score_*`), adjustment flags (`adj_*`), study metadata. Input to everything in `analysis/` |
| `classifications.csv` | Title/abstract classifier output for every screened record. Sets the eligibility denominator |
| `corpus.csv`, `corpus_routed.csv` | Bibliographic metadata and full-text routing |
| `panel_dict.csv`, `panel_anchors.csv` | The 36-item covariate panel and its scoring anchors |
| `exclusions_fulltext.csv` | Studies excluded at full text, by identifier and reason |
| `prisma_checklist.csv` | PRISMA 2020 items and their locations |
| `kappa/` | Blinded expert coding sheets and answer keys |
| `reextract/comparison.csv` | Re-scored sample: run-to-run repeatability and reasoning-effort sensitivity |

### Removed before publication

| Item | Reason |
|---|---|
| `abstract` column | Abstracts are publisher copyright. NLM grants no redistribution right |
| `senior_affiliation` column | PubMed affiliation strings carry corresponding authors' email addresses. `country`, derived from it, is retained |
| `data/fulltext/` | Licensed under institutional subscriptions and text-mining agreements that permit analysis, not republication |
| Batch API payloads | They embed article text |

Every audited study is identified by PubMed ID and DOI, so the corpus can be reconstructed by anyone
with equivalent access.

## Method

Studies analysing CLAD as an outcome (PubMed, 2005-2026) were screened by a title/abstract classifier,
retrieved in full text, and scored by a language model against a pre-specified 36-item covariate panel.
The panel contains a five-item minimum immunological set: CMV donor/recipient serostatus, HLA mismatch,
maintenance immunosuppression, acute cellular rejection burden, and antibody-mediated rejection.

Three constraints govern the extraction:

- **Every non-zero score requires a verbatim supporting quote.** Without an item-specific quote, the
  score is 0.
- **Composite quantities are computed in code**, never by the model.
- **Scoring was validated against blinded expert coding** on a stratified subset: weighted kappa 0.92
  over 450 item judgements. The title/abstract classifier was validated separately.

Language models are not a validated substitute for human extraction in evidence synthesis. Run-to-run
repeatability is therefore measured rather than assumed; see `data/reextract/comparison.csv`.

## Upstream pipeline

`src/clad_audit/` produced `analysis_frame.csv` from PubMed. You do not need it to reproduce the
exhibits. It requires API keys (see `.env.example`) and licensed full texts, which are not included.

```sh
uv sync                                   # Python 3.12+
uv run python -m clad_audit.harvest       # discovery; see src/clad_audit/ for later stages
```

## Citation

El Husseini K, et al. *Reporting of immunological determinants in chronic lung allograft dysfunction
studies: a systematic audit of 1,060 studies.* Details on acceptance.

## Licence

| Component | Licence |
|---|---|
| Code | MIT (`LICENSE`) |
| Derived data in `data/` | CC BY 4.0 (`LICENSE-DATA`) |

Bibliographic metadata originates from PubMed/NLM.
