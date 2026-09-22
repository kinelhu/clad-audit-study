# _coverage.R  (sourced helper, not a numbered stage)
# -----------------------------------------------------------------------
# Single source of the eligible-universe / retrieval-coverage numbers.
# The abstract classifier (data/classifications.csv) covers ALL screened records,
# so it lets us (a) DEFINE eligibility from the title/abstract and (b) test whether
# the retrieved full-text set is representative of the eligible literature it samples.
#
# The abstract gate is deliberately a SUPERSET of "analyzable": on the 690 eligible
# records we did retrieve, every one of the 485 analyzable studies passes it (0 false
# negatives), and 70.3% of gate-passers are analyzable. So gate-passing bounds the
# eligible universe from above, and the observed yield calibrates how many analyzable
# studies the un-retrieved (paywalled) tail is expected to hold.
#
# Exposes: cov_universe (one row per screened record, tagged eligible/retrieved) + the
# counts n_identified, n_screened, n_eligible, n_ineligible, n_retr_elig, n_notretr_elig,
# n_analyzable_cov, n_excl_ft, elig_yield, n_est_miss_an.
# (Frame is NOT named `cov` — that collides with stats::cov(), so exists("cov") is always TRUE.)
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

if (!exists("cov_universe")) {
  # Abstract-only eligibility gate (derivable without full text). Matches the study-
  # structure gate in 00_setup.R minus the two full-text-only calls (outcome_role and
  # the exposure->CLAD estimate): human clinical, and not a review/methods/case report
  # or an animal/in-vitro study.
  abs_gate <- function(clinical, study_type, species)
    (clinical %in% TRUE) &
    !(tolower(study_type) %in% c("methods_or_review", "case_report_series")) &
    !(tolower(species)    %in% c("animal", "in_vitro"))

  .corpus <- readr::read_csv(file.path(project_root, "data/corpus.csv"), show_col_types = FALSE) |>
    dplyr::select(pmid, year, era, journal, is_multicenter_or_registry)
  .cls <- readr::read_csv(file.path(project_root, "data/classifications.csv"), show_col_types = FALSE) |>
    dplyr::select(pmid, clinical, study_type, species, evaluates_intervention, sample_n, study_design)

  cov_universe <- .corpus |>
    dplyr::left_join(.cls, by = "pmid") |>
    dplyr::mutate(eligible  = abs_gate(clinical, study_type, species),
                  retrieved = pmid %in% af$pmid)

  n_identified     <- as.integer(readLines(file.path(project_root, "data/raw/pubmed/_count.txt"))[1])
  n_screened       <- nrow(cov_universe)
  n_eligible       <- sum(cov_universe$eligible)
  n_ineligible     <- n_screened - n_eligible
  n_retr_elig      <- sum(cov_universe$eligible & cov_universe$retrieved)
  n_notretr_elig   <- n_eligible - n_retr_elig
  # analyzable that sit inside the eligible universe (should equal nrow(an); 0 false negatives)
  n_analyzable_cov <- sum(an$pmid %in% cov_universe$pmid[cov_universe$eligible])
  n_excl_ft        <- n_retr_elig - n_analyzable_cov       # eligible + retrieved, excluded on reading
  elig_yield       <- n_analyzable_cov / n_retr_elig       # analyzable per retrieved eligible study
  n_est_miss_an    <- round(n_notretr_elig * elig_yield)   # expected analyzable hidden in the paywalled tail

  if (n_analyzable_cov != nrow(an))
    warning(sprintf("_coverage.R: %d analyzable studies fall outside the abstract gate (expected 0); check the gate.",
                    nrow(an) - n_analyzable_cov))

  message(sprintf(paste0("_coverage.R: identified %d -> screened %d -> eligible %d (%d ineligible) | ",
                         "retrieved %d (analyzable %d, yield %.1f%%) + not-retrieved %d (est. ~%d analyzable). ",
                         "Retrieval coverage of eligible studies = %.1f%%."),
                  n_identified, n_screened, n_eligible, n_ineligible,
                  n_retr_elig, n_analyzable_cov, 100 * elig_yield, n_notretr_elig, n_est_miss_an,
                  100 * n_retr_elig / n_eligible))
}
