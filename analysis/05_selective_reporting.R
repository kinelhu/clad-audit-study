# 05_selective_reporting.R  (EXPLORATORY bias probe)
# -----------------------------------------------------------------------
# Is there evidence of selective reporting — do studies that report a SIGNIFICANT
# exposure->CLAD effect report covariates more (or less) completely? Because
# significance is dominated by sample size, the only defensible test adjusts for it:
# logistic model P(significant) ~ interpretability + log(sample size) + design.
# A null (completeness does not predict significance) is the reassuring result.
# Output: a small table; reported in text, not as a headline figure.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

eff <- an |>
  filter(!is.na(exposure_significant), !is.na(primary_exposure), primary_exposure != "",
         !is.na(sample_size), sample_size > 0, !is.na(study_design)) |>
  # collapse sparse designs into the EXISTING lowercase "other" (fct_lump_min's default "Other" would
  # otherwise sit alongside study_design's own "other" as a duplicate level), ref = retrospective cohort.
  mutate(logN = log(sample_size),
         design = relevel(fct_lump_min(fct_drop(study_design), 15, other_level = "other"),
                          ref = "retrospective_cohort"))

m <- glm(exposure_significant ~ n_minset + logN + design, data = eff, family = binomial)
tid <- broom::tidy(m, exponentiate = TRUE, conf.int = TRUE) |>
  filter(term != "(Intercept)") |>
  transmute(Term = recode(term,
              "n_minset" = "Minimum-set items reported (per item)",
              "logN" = "Sample size (per e-fold)",
              "designrct" = "Design: RCT", "designprospective_cohort" = "Design: prospective cohort",
              "designregistry" = "Design: registry", "designother" = "Design: other",
              "designcross_sectional" = "Design: cross-sectional", .default = term),
            `Odds ratio` = sprintf("%.2f", estimate),
            `95% CI` = sprintf("%.2f–%.2f", conf.low, conf.high), `p` = fmt_p(p.value))
save_df_tbl(tid, "T_selective_reporting",
            caption = "Predictors of reporting a significant exposure-to-CLAD effect (selective-reporting probe)",
            footer = sprintf(paste0("Logistic regression of whether a study reported a statistically significant ",
              "exposure-to-CLAD association, on the minimum-set count, sample size, and study design (n = %s studies ",
              "reporting a primary exposure and a significance call; %s of these fit no exposure-to-CLAD regression, ",
              "so their significance call comes from a bare comparison rather than a model). Odds ratio is per ",
              "additional minimum-set item ",
              "and per e-fold sample size. Design reference category: retrospective cohort. Exploratory. ",
              "*Abbreviations:* CI, confidence interval; CLAD, chronic lung allograft dysfunction; RCT, ",
              "randomized controlled trial."), nrow(eff), cm(sum(eff$model_type %in% "none"))))

s <- broom::tidy(m) |> filter(term == "n_minset")
message(sprintf("05 complete: n=%d. Min-set count->significance OR per item = %.3f (p=%s).",
                nrow(eff), exp(s$estimate), fmt_p(s$p.value)))
