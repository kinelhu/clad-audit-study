# CLAD reporting audit

Analysis code and derived data for a meta-research audit of how completely the lung-transplant chronic
lung allograft dysfunction (CLAD) literature reports and adjusts for the immunological determinants
needed to interpret a CLAD result.

This repository is the analysis. It does not contain the manuscript.

## Before you begin

Install R 4.6.x. The lockfile pins 144 packages.

## Reproduce the exhibits

```sh
Rscript -e 'renv::restore()'
Rscript analysis/run_all.R
```

`run_all.R` reads `data/analysis_frame.csv` and writes `analysis/tables/` and `analysis/figures/`. It
needs no API keys and no network.

It rebuilds every exhibit in the paper: 5 main figures, 2 main tables, 18 supplementary tables and 3
supplementary figures, plus the validation statistics and some tables the paper does not print.

One script stands down. `18_grounding_sensitivity.R` reads a quote-verification audit that contains
text from the audited articles, so that file is not redistributable and is absent here. The script
reports the skip and the run continues.

Scripts find the repository root by walking up to `renv.lock`, so you can run them from any directory.

## Repository layout

| Path | Contents |
|---|---|
| `analysis/` | R analysis. One numbered script per exhibit family, orchestrated by `run_all.R` |
| `analysis/00_setup.R` | Cohort definition and eligibility gates. Sourced by every other script |
| `src/clad_audit/` | Python pipeline: discovery, retrieval, extraction. `panel.py` is the instrument |
| `data/` | Derived data. See [Data](#data) |
| `tools/` | Machine checks on the extraction: quote grounding and re-scoring stability |

## Data

| File | Contents |
|---|---|
| `analysis_frame.csv` | 1,653 studies x 136 columns: per-item scores (`score_*`), adjustment flags (`adj_*`), study metadata. Input to everything in `analysis/` |
| `classifications.csv` | Title and abstract classifier output for every screened record. Sets the eligibility denominator |
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
| Quote-verification audit | Carries verbatim quotes from the audited articles |
| Batch API payloads | They embed article text |

Every audited study is identified by PubMed ID and DOI, so you can reconstruct the corpus with
equivalent access.

## Method

A title and abstract classifier screened studies analysing CLAD as an outcome (PubMed, 2005-2026).
Each retrieved full text was scored by a language model against a pre-specified 36-item covariate
panel. The panel contains a five-item minimum immunological set: CMV donor and recipient serostatus,
HLA mismatch, maintenance immunosuppression, acute cellular rejection burden, and antibody-mediated
rejection.

Three constraints govern the extraction:

- **Every non-zero score requires a verbatim supporting quote.** Without an item-specific quote, the
  score is 0.
- **Composite quantities are computed in code**, never by the model.
- **Scoring was validated against blinded expert coding** on a stratified subset of 90 studies:
  weighted kappa 0.92 over 450 item judgements. The classifier was validated separately.

Language models are not a validated substitute for human extraction in evidence synthesis. The
repository therefore measures run-to-run repeatability rather than assuming it. See
`data/reextract/comparison.csv`.

## Upstream pipeline

`src/clad_audit/` produced `analysis_frame.csv` from PubMed. You do not need it to rebuild the
exhibits. It requires API keys, listed in `.env.example`, and licensed full texts, which are not
included.

```sh
uv sync
uv run python -m clad_audit.harvest
```

Run the stages in order:

| Module | Stage |
|---|---|
| `harvest` | Runs the locked PubMed query and caches the metadata |
| `normalize` | Parses the cached metadata into one row per study |
| `route` | Resolves each DOI to a full-text source |
| `fetch`, `fetch_epmc`, `fetch_istex`, `fetch_tdm` | Retrieve full text, by tier |
| `classify` | Screens title and abstract, and sets the eligibility gate |
| `extract`, `batch` | Score the full text against the panel in `panel.py` |
| `build_frame` | Flattens the extractions into `data/analysis_frame.csv` |

## Citation

El Husseini K, et al. *Reporting of immunological determinants in chronic lung allograft dysfunction
studies: a systematic audit of 1,060 studies.* Details on acceptance.

## Licence

| Component | Licence |
|---|---|
| Code | MIT (`LICENSE`) |
| Derived data in `data/` | CC BY 4.0 (`LICENSE-DATA`) |

Bibliographic metadata originates from PubMed/NLM.
