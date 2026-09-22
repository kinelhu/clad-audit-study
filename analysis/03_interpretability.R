# 03_interpretability.R
# -----------------------------------------------------------------------
# Pre-specified analysis of reporting completeness. Outcome = how many of the five
# minimum-set items a study reports at all (partial or full) -- k of 5, a bounded
# PROPORTION, not an unbounded count. Quasi-binomial GLM; adjusted ODDS ratios for era
# (has reporting changed since the 2019 consensus?), study design, single- vs
# multi-centre, sample size, interventional design and outcome role.
# Family revised from negative-binomial 2026-08-12 -- see the model block below and the
# reasoning trace in docs/methods.md.
# Output: forest plot of adjusted odds ratios + the 0-5 distribution + a table.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

min_keys <- panel$key[panel$min_set]      # bind here, not inside across(): an inline `<-` there lands in
K_min    <- length(min_keys)              # dplyr's data mask, so K_min could not see it
an <- an |> mutate(n_minset = rowSums(across(all_of(paste0("score_", min_keys)), ~ .x %in% c("partial", "full"))))

# ---- model frame ------------------------------------------------------------
md <- an |>
  filter(!is.na(sample_size), sample_size > 0, !is.na(year), !is.na(study_design)) |>
  mutate(logN = log(sample_size),
         yr10 = (year - 2015) / 10,        # calendar time as a simple linear trend, per decade (centred 2015).
                                           # Replaces the pre/post-2019 binary + segmented ITS: the 2019 ISHLT
                                           # consensus defined CLAD, it was not a reporting guideline, so a
                                           # discontinuity there is not a hypothesis worth the machinery.
         design = relevel(fct_drop(fct_collapse(study_design, other = c("other", "cross_sectional"))),
                          ref = "retrospective_cohort"),
         # multi-centre EXCLUDING registries — registries are represented by the design term, so including
         # them here too would double-count. Labelled plainly "Multi-centre" (no longer collides with Design: registry).
         multicentre = factor(if_else(is_multicenter_or_registry & !(study_design %in% "registry"),
                                      "Multi-centre", "Single-centre"), levels = c("Single-centre", "Multi-centre")),
         interventional = factor(if_else(is_interventional, "Interventional", "Observational"),
                                 levels = c("Observational", "Interventional")),
         role = relevel(fct_drop(outcome_role), ref = "secondary"),
         # funding collapsed: industry-involved (industry or mixed) vs all other, incl. not-stated/
         # unclear. A lower-bound contrast — "other" is dominated by undisclosed funding, so this
         # tests whether the studies with *identifiable* industry money report more completely.
         funding_grp = factor(if_else(funding %in% c("industry", "mixed"), "Industry-involved", "Other / not stated"),
                              levels = c("Other / not stated", "Industry-involved")))

form <- cbind(n_minset, K_min - n_minset) ~ yr10 + design + multicentre + logN + interventional + role + funding_grp
# Primary model = QUASI-BINOMIAL GLM (changed from negative-binomial 2026-08-12; docs/methods.md).
# The outcome is k of K_min binary items, i.e. a bounded proportion, not an unbounded count. Bounded counts are
# UNDER-dispersed relative to Poisson (observed variance/mean = 0.58), and the negative binomial can only represent
# variance >= mean: its theta ran to 91,789 (SE 529,930) — unidentified, pinned against its boundary, numerically
# identical to Poisson, and inflating every SE by ~1/sqrt(0.58). The binomial is the generative model here.
# Quasi- rather than plain binomial because the K_min items are correlated WITHIN a study (thorough papers report
# several, cursory ones few): dispersion 1.18, verified against a 1,000-draw parametric bootstrap under a true
# binomial (null range 0.91-1.11, p < 0.001), so the overdispersion is real, not sampling noise. phi > 1 means plain
# binomial would understate the SEs by ~8%. Point estimates are identical under either; only the SEs differ.
# An author-group random intercept was pre-specified but is singular on the adjusted model (see 07_sensitivity.R).
#
# MODEL CHANGED 2026-08-15: composite quasi-binomial -> ITEM-LEVEL mixed logistic. Two reasons, both from
# blinded peer review (docs/peer-review-2026-08-15.md, point 9).
#   1. The composite estimand is not well defined. A single odds ratio on k-of-5 forces one covariate effect
#      across five determinants whose behaviour differs sharply: per-decade trends run from 0.42 (maintenance
#      IS) to 6.10 (AMR), and the covariate-by-determinant interaction is significant for calendar time
#      (chi2 197, p < 1e-12), design, multi-centre status and outcome role. "No change over time, OR 0.97"
#      was an average over significant opposite-signed effects.
#   2. The dispersion parameter never did what the Methods claimed. Quasi-likelihood phi rescales standard
#      errors; it is not a correlation model. A study random intercept actually models the within-study
#      correlation the composite was invoking phi to handle.
# Conclusions are unchanged and slightly stronger (RCT 1.54 -> 1.87, registry 1.26 -> 1.40, primary role
# 1.18 -> 1.28, calendar time null in both); the exhibits are the same two, refitted.
suppressPackageStartupMessages(library(lme4))
long <- scores_long(md) |>
  filter(min_set, applicable) |>
  mutate(rep = as.integer(score %in% c("partial", "full"))) |>
  left_join(md |> select(pmid, yr10, design, multicentre, logN, interventional, role, funding_grp), by = "pmid")
form_i <- rep ~ yr10 + design + multicentre + logN + interventional + role + funding_grp + (1 | key) + (1 | pmid)
m <- lme4::glmer(form_i, family = binomial, data = long,
                 control = lme4::glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 3e5)))

# Homogeneity: one OR averages five determinants, so test whether that average hides divergence. Reported
# in the Methods and Results rather than left implicit — where it is significant the determinant-specific
# estimates are what a reader should use (T_item_trends / F_item_trends).
# The interaction sub-models below add 4 terms per covariate and often report a singular fit; that is
# expected and does not invalidate the likelihood-ratio test of the fixed-effect interaction. The FITTED
# model above is not singular: study variance 1.08, determinant variance 1.18, study-level ICC 0.19 — the
# within-study correlation the composite invoked its dispersion parameter for is real and is now modelled.
het <- function(v) {
  f0 <- update(form_i, . ~ . + key)
  f1 <- update(f0, as.formula(paste0(". ~ . + ", v, ":key")))
  a <- lme4::glmer(f0, family = binomial, data = long,
                   control = lme4::glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 3e5)))
  b <- lme4::glmer(f1, family = binomial, data = long,
                   control = lme4::glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 3e5)))
  s <- anova(a, b); c(chisq = s$Chisq[2], df = s$Df[2], p = s$`Pr(>Chisq)`[2])
}
het_time <- het("yr10")

# ---- tidy fixed effects to adjusted ODDS ratios ------------------------------
co <- summary(m)$coefficients
est <- co[, 1]; se <- co[, 2]
tcrit <- 1.96                                   # z: the mixed model has no residual-df analogue
rr <- tibble(term = rownames(co), rr = exp(est),
             lo = exp(est - tcrit * se), hi = exp(est + tcrit * se),
             p = 2 * pnorm(-abs(est / se))) |>
  filter(term != "(Intercept)") |>
  mutate(label = recode(term,
    "yr10" = "Calendar time (per decade)",
    "designrct" = "Design: RCT",
    "designprospective_cohort" = "Design: prospective cohort",
    "designregistry" = "Design: registry",
    "designother" = "Design: other / cross-sectional",
    "multicentreMulti-centre" = "Multi-centre",
    "logN" = "Sample size (per e-fold)",
    "interventionalInterventional" = "Interventional design",
    "roleprimary" = "CLAD primary outcome",
    "funding_grpIndustry-involved" = "Industry-involved funding", .default = term))

p_forest <- rr |>
  mutate(label = fct_reorder(label, rr)) |>
  ggplot(aes(rr, label)) +
  geom_vline(xintercept = 1, linetype = 2, colour = "grey55") +
  geom_errorbar(aes(xmin = lo, xmax = hi), width = 0.25, colour = "grey35", orientation = "y") +
  geom_point(colour = clad_blue, size = 2.2) +
  # FIVE BREAKS, NOT SEVEN, AND NO TRAILING ZEROS. Seven four-character labels ("0.60 0.80 1.00 1.25
  # 1.60 2.00 2.60") do not fit the panel this plot gets and printed as "0.801.001.25 1.602.00": the
  # axis was unreadable exactly where the estimates are. Labels are the constraint on a log axis, not
  # break count in the abstract, so these are short and unevenly spaced by design.
  scale_x_log10(breaks = c(0.5, 0.75, 1, 1.5, 2), labels = as.character) +
  labs(x = "Adjusted odds ratio (95% CI)", y = NULL)

# ---- distribution of number of minimum-set items reported (partial or full) --
p_dist <- an |> count(n_minset) |>
  ggplot(aes(factor(n_minset), n)) +
  geom_col(fill = clad_blue, width = 0.82) +
  geom_text(aes(label = n), vjust = -0.3, size = lab_size) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.08))) +
  labs(x = paste0("Minimum-set items reported (of ", K_min, ")"), y = "Studies")

pp <- p_dist + p_forest + patchwork::plot_layout(widths = c(1, 1.5)) +
  patchwork::plot_annotation(tag_levels = "A")
save_fig("F_interpretability", pp, width = fig_w2, height = 3.5)

# table of the model
save_df_tbl(rr |> transmute(Predictor = label, `Odds ratio` = sprintf("%.2f", rr),
                            `95% CI` = sprintf("%.2f–%.2f", lo, hi), `p` = fmt_p(p)),
            "T_minset_model",
            caption = "Adjusted odds ratios for reporting a minimum-set determinant",
            footer = sprintf(paste0("Mixed-effects logistic regression at the study-determinant level (%s ",
              "observations from %s studies with a resolvable year and sample size), with random intercepts ",
              "for study and for determinant; the outcome is whether a determinant was reported at all. An ",
              "odds ratio above 1 indicates more complete reporting. Calendar time is a continuous per-decade ",
              "trend. Reference categories: retrospective cohort, single-centre, observational design, CLAD ",
              "secondary outcome, and other/not-stated funding. Each odds ratio averages the %d determinants, ",
              "and that average conceals real divergence: the calendar-time effect differs across determinants ",
              "(chi-square %.0f on %d degrees of freedom, p %s), so determinant-specific trends are reported ",
              "separately. Author-group clustering is assessed as a sensitivity analysis. *Abbreviations:* CI, ",
              "confidence interval; CLAD, chronic lung allograft dysfunction; RCT, randomized controlled trial."),
                             format(nrow(long), big.mark = ","), format(nrow(md), big.mark = ","),
                             K_min, het_time[["chisq"]], het_time[["df"]], fmt_p(het_time[["p"]])))

write_legend("F_interpretability", paste0(
  "**Figure. Predictors of reporting completeness.** (A) Number of the ", K_min, " minimum-set items each ",
  "analyzable study reports at all (partial or full; n = ", cm(nrow(an)), "). (B) Adjusted odds ratios ",
  "(mixed-effects logistic regression at the study-determinant level, ", format(nrow(long), big.mark = ","),
  " observations from ", format(nrow(md), big.mark = ","), " studies) for reporting a given minimum-set determinant; ",
  "points right of 1 indicate more complete reporting. Calendar time is a continuous per-decade trend; ",
  "reference categories: retrospective cohort, single-centre, observational design, CLAD secondary outcome, ",
  "other/not-stated funding. *Abbreviations:* CI, confidence interval; CLAD, chronic lung allograft dysfunction; ",
  "RCT, randomized controlled trial."))

# Values the manuscript and report quote, persisted so no n or test statistic is retyped in prose.
readr::write_csv(tibble::tibble(n_obs = nrow(long), n_studies = nrow(md),
                                het_chisq = het_time[["chisq"]], het_df = het_time[["df"]],
                                het_p = het_time[["p"]], icc_study = {
                                  vc <- as.data.frame(lme4::VarCorr(m))
                                  vc$vcov[vc$grp == "pmid"] / (sum(vc$vcov) + pi^2 / 3) }),
                 file.path(dir_tables, "_model_stats.csv"))

yr_rr <- rr |> filter(term == "yr10")
message(sprintf(paste0("03 complete: item-level mixed logistic, %d obs / %d studies. Calendar-time OR per ",
                       "decade = %.2f (95%% CI %.2f–%.2f, p=%s); effect differs across determinants ",
                       "(chi2 %.0f, df %d, p=%s)."),
                nrow(long), nrow(md), yr_rr$rr, yr_rr$lo, yr_rr$hi, fmt_p(yr_rr$p),
                het_time[["chisq"]], het_time[["df"]], fmt_p(het_time[["p"]])))
