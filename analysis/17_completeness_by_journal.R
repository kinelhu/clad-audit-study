# 17_completeness_by_journal.R
# Minimum-set completeness by publishing journal.
#
# WHY. The cover letter says 18% of the audited corpus appeared in JHLT, the largest share of any
# journal, and the paper never reports completeness by journal. A board member reading an audit of a
# literature its own journal dominates will want the number, and a reviewer can ask for it. Computed
# here so the answer is a table, not a guess (simulated review 2026-09-21, decision-table row 34).
#
# DISCLOSURE RULE, set before the number was seen (docs/peer-review-2026-09-21.md, political angle):
# if JHLT is at or above the corpus on both the median count and the share reporting none, the cover
# letter may say so in one sentence; if below on either, the number stays in analysis/tables and the
# letter keeps its system-level framing. `_journal_stats.csv` carries the decision fields.
#
# WHAT. Journals with at least JOURNAL_MIN analyzable studies get a row; the rest are pooled as
# "All other journals". Descriptive columns are the minimum-set count and the per-item reported share
# among applicable studies. The adjusted column is the study-determinant mixed model of
# 03_interpretability.R with the journal factor added, reference "All other journals", so each odds
# ratio is a journal's reporting odds against the pooled remainder, net of design, centre status,
# size, interventional design, outcome role, funding and calendar time.

if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))
suppressPackageStartupMessages(library(lme4))

JOURNAL_MIN <- 25

min_keys <- panel$key[panel$min_set]
K_min    <- length(min_keys)
an <- an |> mutate(n_minset = rowSums(across(all_of(paste0("score_", min_keys)), ~ .x %in% c("partial", "full"))))

# Short labels for the PubMed full titles. A journal not matched here keeps its PubMed title, so an
# unmatched title shows up in the table rather than silently pooling.
short_journal <- function(j) {
  case_when(
    str_detect(j, regex("^The Journal of heart and lung transplantation", ignore_case = TRUE)) ~ "J Heart Lung Transplant",
    str_detect(j, regex("^JHLT open", ignore_case = TRUE))                                       ~ "JHLT Open",
    str_detect(j, regex("^American journal of transplantation", ignore_case = TRUE))             ~ "Am J Transplant",
    str_detect(j, regex("^Transplantation$", ignore_case = TRUE))                                ~ "Transplantation",
    str_detect(j, regex("^Transplantation proceedings", ignore_case = TRUE))                     ~ "Transplant Proc",
    str_detect(j, regex("^Clinical transplantation", ignore_case = TRUE))                        ~ "Clin Transplant",
    str_detect(j, regex("^Transplant international", ignore_case = TRUE))                        ~ "Transpl Int",
    str_detect(j, regex("^American journal of respiratory and critical care", ignore_case = TRUE)) ~ "Am J Respir Crit Care Med",
    str_detect(j, regex("^Transplant immunology", ignore_case = TRUE))                           ~ "Transpl Immunol",
    str_detect(j, regex("^The Annals of thoracic surgery", ignore_case = TRUE))                  ~ "Ann Thorac Surg",
    str_detect(j, regex("^Transplantation direct", ignore_case = TRUE))                          ~ "Transplant Direct",
    str_detect(j, regex("^European journal of cardio-thoracic surgery", ignore_case = TRUE))     ~ "Eur J Cardiothorac Surg",
    str_detect(j, regex("^The Journal of thoracic and cardiovascular surgery", ignore_case = TRUE)) ~ "J Thorac Cardiovasc Surg",
    str_detect(j, regex("^Transplant infectious disease", ignore_case = TRUE))                   ~ "Transpl Infect Dis",
    str_detect(j, regex("^The European respiratory journal", ignore_case = TRUE))                ~ "Eur Respir J",
    TRUE ~ j
  )
}

jd <- an |>
  mutate(journal_s = short_journal(journal)) |>
  add_count(journal_s, name = "n_j") |>
  mutate(journal_g = if_else(n_j >= JOURNAL_MIN, journal_s, "All other journals"))

named  <- jd |> filter(journal_g != "All other journals") |> count(journal_g, sort = TRUE) |> pull(journal_g)
n_other_journals <- jd |> filter(journal_g == "All other journals") |> distinct(journal) |> nrow()
jd <- jd |> mutate(journal_g = factor(journal_g, levels = c(named, "All other journals")))

# ---- descriptive block -------------------------------------------------------------------------------
item_lab <- if ("label" %in% names(panel)) setNames(panel$label, panel$key) else setNames(panel$key, panel$key)

per_item <- scores_long(jd) |>
  filter(min_set, applicable) |>
  mutate(rep = score %in% c("partial", "full")) |>
  left_join(jd |> select(pmid, journal_g), by = "pmid") |>
  group_by(journal_g, key) |>
  summarise(p = mean(rep), .groups = "drop") |>
  mutate(col = paste0(item_lab[key], " reported"), p = sprintf("%.0f%%", 100 * p)) |>
  select(-key) |>
  pivot_wider(names_from = col, values_from = p)

desc_one <- function(d, label) {
  tibble(Journal = label,
         `Studies, n (%)` = sprintf("%d (%.0f%%)", nrow(d), 100 * nrow(d) / nrow(jd)),
         `Minimum-set items, median [IQR]` = sprintf("%.0f [%.0f–%.0f]", median(d$n_minset),
                                                   quantile(d$n_minset, .25), quantile(d$n_minset, .75)),
         `Reported none, n (%)` = n_pct(d$n_minset == 0))
}
desc <- bind_rows(
  lapply(levels(jd$journal_g), \(g) desc_one(jd |> filter(journal_g == g), g)),
  desc_one(jd, "All studies")
)
per_item_all <- scores_long(jd) |>
  filter(min_set, applicable) |> mutate(rep = score %in% c("partial", "full")) |>
  group_by(key) |> summarise(p = mean(rep), .groups = "drop") |>
  mutate(col = paste0(item_lab[key], " reported"), p = sprintf("%.0f%%", 100 * p)) |>
  select(-key) |> pivot_wider(names_from = col, values_from = p) |> mutate(journal_g = "All studies")
per_item <- bind_rows(per_item |> mutate(journal_g = as.character(journal_g)), per_item_all)

# ---- adjusted block: the 03_interpretability.R model plus the journal factor -----------------------
md <- jd |>
  filter(!is.na(sample_size), sample_size > 0, !is.na(year), !is.na(study_design)) |>
  mutate(logN = log(sample_size),
         yr10 = (year - 2015) / 10,
         design = relevel(fct_drop(fct_collapse(study_design, other = c("other", "cross_sectional"))),
                          ref = "retrospective_cohort"),
         multicentre = factor(if_else(is_multicenter_or_registry & !(study_design %in% "registry"),
                                      "Multi-centre", "Single-centre"), levels = c("Single-centre", "Multi-centre")),
         interventional = factor(if_else(is_interventional, "Interventional", "Observational"),
                                 levels = c("Observational", "Interventional")),
         role = relevel(fct_drop(outcome_role), ref = "secondary"),
         funding_grp = factor(if_else(funding %in% c("industry", "mixed"), "Industry-involved", "Other / not stated"),
                              levels = c("Other / not stated", "Industry-involved")),
         journal_g = relevel(journal_g, ref = "All other journals"))

long <- scores_long(md) |>
  filter(min_set, applicable) |>
  mutate(rep = as.integer(score %in% c("partial", "full"))) |>
  left_join(md |> select(pmid, journal_g, yr10, design, multicentre, logN, interventional, role, funding_grp), by = "pmid")
form_j <- rep ~ journal_g + yr10 + design + multicentre + logN + interventional + role + funding_grp + (1 | key) + (1 | pmid)
mj <- lme4::glmer(form_j, family = binomial, data = long,
                  control = lme4::glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 3e5)))
co <- summary(mj)$coefficients
adj <- tibble(term = rownames(co), est = co[, "Estimate"], se = co[, "Std. Error"], p = co[, "Pr(>|z|)"]) |>
  filter(str_starts(term, "journal_g")) |>
  mutate(Journal = str_remove(term, "^journal_g"),
         or = exp(est), lo = exp(est - 1.96 * se), hi = exp(est + 1.96 * se),
         `Adjusted OR vs other journals (95% CI)` = sprintf("%.2f (%.2f–%.2f)", or, lo, hi)) |>
  select(Journal, `Adjusted OR vs other journals (95% CI)`, or, lo, hi, p)
stopifnot(nrow(adj) == length(named))   # every named journal got a coefficient; a dropped level would be silent

tab <- desc |>
  left_join(per_item, by = c("Journal" = "journal_g")) |>
  left_join(adj |> select(Journal, `Adjusted OR vs other journals (95% CI)`), by = "Journal") |>
  mutate(`Adjusted OR vs other journals (95% CI)` = case_when(
    Journal == "All other journals" ~ "1 (reference)",
    Journal == "All studies" ~ "",
    TRUE ~ `Adjusted OR vs other journals (95% CI)`))

save_df_tbl(tab, "T_minset_by_journal",
  caption = sprintf("Minimum-set reporting by publishing journal (%d analyzable studies)", nrow(jd)),
  footer = sprintf(paste0(
    "Journals with at least %d analyzable studies are shown; the remaining %d journals are pooled. Minimum-set ",
    "items are counted as reported when scored partial or full. Per-item shares are over applicable studies. ",
    "The adjusted odds ratio is from the study-determinant mixed-effects logistic model of Supplementary Table S3 ",
    "with the journal added as a factor (reference: all other journals), so it is net of calendar time, design, ",
    "multi-centre status, sample size, interventional design, outcome role and funding; %s observations from %s studies."),
    JOURNAL_MIN, n_other_journals, cm(nrow(long)), cm(n_distinct(long$pmid))),
  landscape = TRUE)

# ---- decision fields for _setup.R and the cover-letter rule ---------------------------------------
jh   <- jd |> filter(journal_g == "J Heart Lung Transplant")
jadj <- adj |> filter(Journal == "J Heart Lung Transplant")
stopifnot(nrow(jh) > 0, nrow(jadj) == 1)
stats <- tibble(
  journal_min          = JOURNAL_MIN,
  n_named_journals     = length(named),
  n_other_journals     = n_other_journals,
  jhlt_n               = nrow(jh),
  jhlt_share           = nrow(jh) / nrow(jd),
  jhlt_median          = median(jh$n_minset),
  all_median           = median(jd$n_minset),
  jhlt_none_pct        = 100 * mean(jh$n_minset == 0),
  all_none_pct         = 100 * mean(jd$n_minset == 0),
  jhlt_or              = jadj$or, jhlt_lo = jadj$lo, jhlt_hi = jadj$hi, jhlt_p = jadj$p,
  jhlt_at_or_above     = (median(jh$n_minset) >= median(jd$n_minset)) & (mean(jh$n_minset == 0) <= mean(jd$n_minset == 0))
)
readr::write_csv(stats, file.path(dir_tables, "_journal_stats.csv"))
message(sprintf("JHLT: %d studies (%.0f%%), median %d vs %d, none %.0f%% vs %.0f%%, adjusted OR %.2f (%.2f–%.2f); at or above corpus: %s",
                stats$jhlt_n, 100 * stats$jhlt_share, stats$jhlt_median, stats$all_median,
                stats$jhlt_none_pct, stats$all_none_pct, stats$jhlt_or, stats$jhlt_lo, stats$jhlt_hi, stats$jhlt_at_or_above))
