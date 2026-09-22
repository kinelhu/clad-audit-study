# 07_sensitivity.R
# -----------------------------------------------------------------------
# Two robustness checks, reported compactly:
#  (a) source-format extraction check — %full for table-based items by XML vs PDF
#      (a large XML>PDF gap would mean the LLM under-reads PDF tables). Table only.
#  (b) reporting-habit clustering — min-set-count ICC by author group.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))
suppressPackageStartupMessages(library(lme4))

# ---- (a) source-format check (table) ----------------------------------------
tbl_items <- c("hla_mismatch", "cmv_dr", "acr", "pgd")
sf <- an |>
  select(pmid, source_format, all_of(paste0("score_", tbl_items))) |>
  pivot_longer(starts_with("score_"), names_prefix = "score_", names_to = "key", values_to = "score") |>
  filter(source_format %in% c("xml", "pdf"), score %in% c("not", "partial", "full")) |>
  left_join(panel, by = "key") |>
  group_by(Covariate = label, Source = toupper(source_format)) |>
  summarise(N = n(), `% Full` = pct(mean(score == "full")), `% Not reported` = pct(mean(score == "not")),
            .groups = "drop") |>
  arrange(Covariate, Source)
save_df_tbl(sf, "T_sensitivity_source",
            caption = "Reporting of table-based covariates by full-text source format (extraction-format check)",
            footer = paste0("Reporting rates for table-based items among studies whose full text was structured XML ",
              "versus PDF-derived text, bounding the risk that a 'not reported' score reflects extraction failure ",
              "rather than true omission. *Abbreviations:* ACR, acute cellular rejection; CMV, cytomegalovirus; ",
              "D/R, donor/recipient; HLA, human leucocyte antigen; PDF, portable document format; PGD, primary graft ",
              "dysfunction; XML, extensible markup language."))

# ---- (b) reporting-habit clustering (author-group ICC) ----------------------
# UNADJUSTED clustering only. An author-group random intercept was pre-specified for the primary model, but on the
# adjusted model its variance collapses to ~0 (singular fit) — the study-level covariates absorb this clustering, so
# the primary model (03_interpretability.R) carries random intercepts for study and determinant only, and this ICC
# is reported as a sensitivity instead. Reasoning trace: docs/methods.md (2026-08-08, model revised 2026-08-15).
d <- an |> filter(!is.na(group_key), group_key != "")
m <- lmer(n_minset ~ 1 + (1 | group_key), data = d)
vc <- as.data.frame(VarCorr(m)); icc <- vc$vcov[vc$grp == "group_key"] / sum(vc$vcov)
save_df_tbl(
  an |> group_by(`Multi-centre / registry` = ifelse(is_multicenter_or_registry, "Yes", "No")) |>
    summarise(N = n(), `Min-set items, median [IQR]` = med_iqr(n_minset), .groups = "drop"),
  "T_sensitivity_multicentre",
  caption = "Minimum-set reporting by multi-centre / registry status",
  footer = sprintf(paste0("Unadjusted author-group intraclass correlation for the minimum-set count = %.2f (author group = ",
    "senior author + country). This clustering is absorbed by the model covariates: in the adjusted mixed ",
    "logistic model the author-group random-intercept variance is ~0 (singular fit), so the primary model omits it. ",
    "*Abbreviations:* IQR, interquartile range."), icc))

# ---- (c) retrieval representativeness: within the ELIGIBLE UNIVERSE, retrieved vs not ----
# The completeness analysis rests on the eligible studies we could retrieve; the abstract classifier covers ALL
# screened records, so we test whether that retrieved set is representative of the eligible literature it samples.
# Restricting to the eligible universe (abstract gate) is the point: comparing across the whole 1,923 would mix
# in non-clinical/basic-science records and mask the comparison that matters (eligible retrieved vs eligible missed).
source(file.path(dir_analysis, "_coverage.R"))
rep_t <- cov_universe |>
  filter(eligible) |>
  transmute(
    Retrieved = factor(if_else(retrieved, "Retrieved", "Not retrieved"), levels = c("Retrieved", "Not retrieved")),
    Year = year,
    Era = fct_recode(factor(era), "Pre-2019" = "pre", "2019+" = "post"),
    # only four study types survive the abstract gate (reviews/methods/case reports are excluded by it)
    `Study type` = fct_recode(factor(study_type),
        "Clinical cohort" = "clinical_cohort", "Mechanistic / translational" = "mechanistic_translational",
        "Registry" = "registry", "Trial" = "trial"),
    `Evaluates intervention` = evaluates_intervention %in% TRUE,
    `Multi-centre / registry` = is_multicenter_or_registry,
    `Sample size` = sample_n) |>
  tbl_summary(by = Retrieved, missing = "no",
    statistic = list(all_continuous() ~ "{median} [{p25}-{p75}]", all_categorical() ~ "{n} ({p}%)")) |>
  add_p() |> modify_header(label = "**Characteristic**") |> bold_labels()
save_tbl(rep_t, "T_representativeness",
         footer = sprintf(paste0("Eligible studies (abstract-defined, n = %s) with vs without retrievable full text, ",
           "compared on title/abstract-classifier fields (available for every screened record). ",
           "p-values from Wilcoxon (continuous) / chi-square (categorical). The non-retrieved group is small, so ",
           "these comparisons are exposed to type II rather than type I error: a null p-value here means no ",
           "difference was detectable, not that none exists. Read effect sizes, not stars."), format(n_eligible, big.mark = ",", trim = TRUE)))

# ---- (d) analytic validity of the time-to-event CLAD analysis (domain-specific rigor) ----
# CLAD is a time-to-event outcome with time-varying exposures and a strong competing risk (death), so two
# CLAD-specific pitfalls matter: immortal-time bias (time-varying exposures treated as fixed) and ignoring the
# competing risk of death (Kaplan-Meier then over-states CLAD incidence). We already extract both.
tte <- an |> filter(survival_method %in% c("km_logrank", "cox_ph", "competing_risk"))
cr_ok  <- tte$survival_method == "competing_risk" | tte$score_competing_risk == "full"
# TIME-VARYING COVARIATES NEED A REGRESSION. Kaplan-Meier with log-rank cannot carry a time-dependent
# covariate at all, so counting time-varying modelling over every time-to-event study divides by a
# denominator in which a large share of studies COULD NOT have done it: 140/785 = 18% understates the
# practice roughly two-fold against 140/343 = 41% among the time-to-event studies that fit a
# multivariable model. Competing risk keeps the full 785 — a cumulative-incidence function applies to a
# descriptive analysis too, so there the wider denominator is the right one. (Peer review 2026-08-15.)
tvc_den <- tte |> filter(model_type %in% "multivariable")
tvc_ok  <- tvc_den$time_varying_covariates == "yes"
# Events per variable, among the studies that fit a multivariable CLAD model. Reported because a low EPV is a
# legitimate alternative explanation for not entering the determinants: a small, event-poor cohort that declines
# to add five covariates is modelling conservatively, not neglecting confounders. Conceding that makes the
# residual gap stronger rather than weaker.
epv <- suppressWarnings(as.numeric(an$events_per_variable[an$model_type %in% "multivariable"]))
epv <- epv[is.finite(epv)]
rigor <- tibble(
  Metric = c("Time-to-event CLAD analysis (denominator)",
             "Competing risk of death formally addressed",
             "Time-varying exposure modelled (immortal-time guard), of multivariable models",
             "Events per variable, multivariable models (median [IQR])",
             "Multivariable models with < 10 events per variable"),
  `n (%)` = c(as.character(nrow(tte)),
              sprintf("%d (%s)", sum(cr_ok),  pct(mean(cr_ok))),
              sprintf("%d/%d (%s)", sum(tvc_ok), nrow(tvc_den), pct(mean(tvc_ok))),
              if (length(epv)) sprintf("%.1f [%.1f–%.1f]", median(epv), quantile(epv, .25), quantile(epv, .75)) else "not reported",
              if (length(epv)) sprintf("%d/%d (%s)", sum(epv < 10), length(epv), pct(mean(epv < 10))) else "not reported"))
save_df_tbl(rigor, "T_analytic_rigor",
            caption = "Analytic validity of the time-to-event CLAD analysis",
            footer = sprintf(paste0("Competing-risk handling is reported over all %s analyzable studies using a ",
              "time-to-event method for CLAD (Kaplan-Meier/log-rank, Cox, or competing-risk), because a ",
              "cumulative-incidence function applies to a descriptive analysis as well; it addresses the competing ",
              "risk of death, which otherwise makes Kaplan-Meier over-state cumulative CLAD incidence. ",
              "Time-varying modelling, which guards against immortal-time bias, is reported over the %s of those ",
              "studies that fit a multivariable model, since Kaplan-Meier with log-rank cannot carry a ",
              "time-dependent covariate. Key exposures (rejection, DSA, infection) are time-varying. ",
              "The two events-per-variable rows have a different denominator again: they are among the ",
              "%s studies fitting a multivariable CLAD model that report both their CLAD event count and the number ",
              "of covariates in the model. A low value is a reason to model sparingly, and is given so that ",
              "non-adjustment is not read as neglect alone. ",
              "*Abbreviations:* CLAD, chronic lung allograft dysfunction; DSA, donor-specific antibody; IQR, ",
              "interquartile range."),
              cm(nrow(tte)), cm(nrow(tvc_den)), cm(length(epv))))

# ---- (d2) composition of the minimum set ------------------------------------------------------
# Two objections answered with one computation, reported as numbers in the text rather than a table.
# (i) Is the finding an artefact of which five determinants were chosen? Leave each out in turn.
# (ii) Should the alloantibody slot be de novo DSA rather than AMR (DSA is measured near-universally,
#      pulmonary AMR needs biopsy and consensus criteria many centres cannot apply)? Substitute and see.
.rep <- function(k) an[[paste0("score_", k)]] %in% c("partial", "full")
.cnt <- function(keys) rowSums(sapply(keys, .rep))
.none <- function(keys) mean(.cnt(keys) == 0)
base_keys <- min_set_keys
loo <- vapply(base_keys, function(k) .none(setdiff(base_keys, k)), numeric(1))
dsa_keys <- c(setdiff(base_keys, "amr"), "de_novo_dsa")
readr::write_csv(tibble::tibble(
  none_base      = .none(base_keys),
  none_dsa       = .none(dsa_keys),
  none_loo_min   = min(loo), none_loo_max = max(loo),
  loo_min_item   = panel$label[match(names(which.min(loo)), panel$key)],
  loo_max_item   = panel$label[match(names(which.max(loo)), panel$key)],
  rep_amr        = mean(.rep("amr")), rep_dsa = mean(.rep("de_novo_dsa"))),
  file.path(dir_tables, "_minset_composition.csv"))

# ---- (e) eligibility sensitivity: broad (structure-based) vs narrow (clinical cohorts/trials/registries only) ----
# The primary cohort is structure-based: it KEEPS mechanistic/translational studies that estimate an
# exposure->CLAD effect (dd-cfDNA, DSA, gene-expression biomarker cohorts). A reviewer may worry those inflate
# "not reported". The narrow cohort drops ALL mechanistic_translational, keeping only clinical cohorts, trials,
# and registries. If the headline holds across both, it is not an artifact of the eligibility call.
det_keys <- setdiff(min_set_keys, "clad_definition")          # the 5 immunological determinants
elig_metrics <- function(d) {
  pnot <- vapply(det_keys, function(k) {
    s <- d[[paste0("score_", k)]]; s <- s[s %in% c("not", "partial", "full")]
    pct(mean(s == "not"))
  }, character(1))
  c(N = as.character(nrow(d)),
    `Min-set items reported, median [IQR]` = med_iqr(d$n_minset),
    setNames(pnot, as.character(panel$label[match(det_keys, panel$key)])),
    `Fitted a multivariable CLAD model` = pct(mean(d$model_type == "multivariable")))
}
an_narrow <- an |> filter(study_type %in% c("clinical_cohort", "trial", "registry"))
mb <- elig_metrics(an); mn <- elig_metrics(an_narrow)
elig <- tibble(Metric = names(mb), `Broad (primary)` = unname(mb), `Narrow` = unname(mn[names(mb)]))
save_df_tbl(elig, "T_eligibility_sensitivity",
  caption = "Robustness of the headline findings to the eligibility definition",
  footer = sprintf(paste0("Broad (n = %s) is the primary structure-based cohort: patient-level studies estimating ",
    "an exposure-CLAD effect, including prognostic biomarker / mechanistic cohorts that carry such an estimate. ",
    "Narrow (n = %s) keeps only clinical cohorts, trials, and registries, dropping all mechanistic / translational ",
    "studies. Per-item values are %% not reported among studies where the item was applicable; determinant rows are ",
    "the five immunological minimum-set items. *Abbreviations:* ACR, acute cellular rejection; AMR, ",
    "antibody-mediated rejection; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; D/R, ",
    "donor/recipient; HLA, human leucocyte antigen; IQR, interquartile range; IS, immunosuppression."),
    nrow(an), nrow(an_narrow)))

message(sprintf("07 complete: ICC=%.2f; representativeness + analytic-rigor tables written (%d tte: %d%% competing-risk, %d%% time-varying). Eligibility sensitivity: broad n=%d vs narrow n=%d.",
                icc, nrow(tte), round(100*mean(cr_ok)), round(100*mean(tvc_ok)), nrow(an), nrow(an_narrow)))
