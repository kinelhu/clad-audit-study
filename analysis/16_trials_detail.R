# 16_trials_detail.R
# -----------------------------------------------------------------------
# Every randomized trial in the analyzable cohort, one row per REPORT, with its comparator and what
# kind of report it is.
#
# Why: "39 randomized controlled trials" in the corpus table reads to a transplant clinician as a
# well-ploughed field, and a co-author read it exactly that way (2026-08-31). The count is of trial
# REPORTS, and it contains pharmacokinetic substudies, post hoc re-analyses and long-term follow-ups.
# Aggregating them hides that the field has run six trials in established CLAD in twenty-one years. A
# count that misleads the target reader needs the detail under it, not a footnote.
#
# Trial PROTOCOL papers are no longer here at all: they report no results, so they were ineligible under
# the stated audit population and are excluded upstream in 00_setup.R (reason protocol_no_results), which
# also screens for new ones on every build.
#
# PROVENANCE OF THIS TABLE, which is unlike every other exhibit here. Comparator, report type and
# trial grouping are NOT in the extraction schema and are not produced by the language-model
# pipeline. They were read by hand from the title and abstract of each of the records below and
# checked against the abstract by a second author. At this scale that is the honest instrument;
# adding three fields to a 36-item panel and re-extracting 1,063 papers to populate them for 37
# would not have been. The footer says so.
#
# Everything else in the row (year, n randomized, intent) is joined from the frame, and the pmid set
# is asserted against it, so this table cannot silently describe a cohort that has moved underneath it.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

# trial_group: reports of the SAME randomized trial share a value. It is what makes the
# reports-versus-trials distinction computable instead of asserted.
hand <- tibble::tribble(
  ~pmid,      ~label,             ~intervention,                                  ~comparator,                        ~report,                        ~trial_group,
  "16407509", "Iacono 2006",      "Inhaled ciclosporin",                          "Placebo aerosol",                  "Primary trial report",         "L-CsA prevention",
  "16433771", "Snell 2006",       "Everolimus",                                   "Azathioprine",                     "Primary trial report",         "Everolimus vs azathioprine",
  "16563975", "Kovarik 2006",     "Everolimus",                                   "Azathioprine",                     "Pharmacokinetic substudy",     "Everolimus vs azathioprine",
  "16612275", "McNeil 2006",      "Mycophenolate mofetil",                        "Azathioprine",                     "Primary trial report",         "MMF vs azathioprine",
  "17613395", "Snell 2007",       "Everolimus",                                   "Azathioprine",                     "Mechanistic substudy",         "Everolimus vs azathioprine",
  "17919621", "Hachem 2007",      "Tacrolimus",                                   "Ciclosporin",                      "Primary trial report",         "Tacrolimus vs ciclosporin (single-centre)",
  "18442722", "Hartwig 2008",     "Rabbit antithymocyte globulin induction",      "No induction",                     "Primary trial report",         "RATG induction",
  "19580368", "Groves 2010",      "Inhaled ciclosporin",                          "Placebo aerosol",                  "Secondary analysis",           "L-CsA prevention",
  "20562124", "Vos 2011",         "Azithromycin prophylaxis",                     "Placebo",                          "Primary trial report",         "Azithromycin prophylaxis (Leuven)",
  "20833822", "Bhorade 2011",     "Sirolimus",                                    "Azathioprine",                     "Primary trial report",         "Sirolimus vs azathioprine",
  "20851929", "Zamora 2011",      "Aerosolised ALN-RSV01",                        "Placebo",                          "Primary trial report",         "ALN-RSV01 phase 2a",
  "22554673", "Treede 2012",      "Tacrolimus",                                   "Ciclosporin",                      "Primary trial report",         "Tacrolimus vs ciclosporin (multicentre)",
  "25039364", "Jaksch 2014",      "Alemtuzumab induction, reduced maintenance",   "Thymoglobulin, standard maintenance", "Primary trial report",      "Alemtuzumab induction",
  "25049068", "Glanville 2015",   "Everolimus, delayed onset",                    "Enteric-coated mycophenolate sodium", "Primary trial report",      "Everolimus vs mycophenolate sodium",
  "26372728", "Ruttens 2016",     "Azithromycin prophylaxis",                     "Placebo",                          "Post hoc analysis",            "Azithromycin prophylaxis (Leuven)",
  "26452996", "Gottlieb 2016",    "Aerosolised ALN-RSV01",                        "Placebo",                          "Primary trial report",         "ALN-RSV01 phase 2b",
  "27104933", "Strueber 2016",    "Everolimus",                                   "Mycophenolate mofetil",            "Primary trial report",         "Everolimus vs MMF",
  "27664940", "Rosenberger 2017", "Pocket PATH mobile health self-management",    "Usual care",                       "Long-term follow-up",          "Pocket PATH",
  "28365177", "Vos 2017",         "Vitamin D, once monthly oral",                 "Placebo",                          "Primary trial report",         "Vitamin D",
  "30247316", "Westall 2019",     "QuantiFERON-CMV-directed valganciclovir",      "Fixed-duration valganciclovir",    "Primary trial report",         "QuantiFERON-CMV-directed prophylaxis",
  "30615259", "Gottlieb 2019",    "Everolimus, quadruple low-calcineurin",        "Standard triple calcineurin",      "Primary trial report",         "Everolimus quadruple low-CNI",
  "30686699", "Van Herck 2019",   "Azithromycin, peri-transplant",                "Placebo",                          "Primary trial report",         "Peri-transplant azithromycin",
  "34587371", "Neurohr 2022",     "Liposomal ciclosporin A for inhalation",       "Placebo",                          "Primary trial report",         "L-CsA phase 3 prevention",
  "34599540", "Sweet 2022",       "Rituximab induction (paediatric)",             "Placebo",                          "Primary trial report",         "CTOTC-08",
  "39638420", "Benazzo 2025",     "Extracorporeal photopheresis, prophylactic",   "Standard triple immunosuppression", "Primary trial report",        "ECP prophylaxis",
  "40453071", "Righi 2025",       "Extracorporeal photopheresis as induction",    "Standard care",                    "Primary trial report (pilot)", "ECP induction",
  "29087035", "Smith 2018",       "None; cognition in trial survivors",           "Not applicable",                   "Secondary analysis",           "INSPIRE-II",
  "29624575", "Ruttens 2018",     "Montelukast",                                  "Placebo",                          "Primary trial report",         "Montelukast",
  "31673366", "Gan 2019",         "Azithromycin",                                 "Placebo",                          "Post hoc, long-term",          "Azithromycin for BOS (Groningen)",
  "31687370", "Iacono 2019",      "Inhaled liposomal ciclosporin",                "Standard of care alone",           "Primary trial report",         "L-CsA for BOS",
  "38741362", "Iacono 2024",      "Inhaled liposomal ciclosporin",                "Standard of care alone",           "Long-term follow-up",          "L-CsA for BOS",
  "38796045", "Combs 2024",       "Pirfenidone (STOP-CLAD)",                      "Placebo",                          "Primary trial report",         "STOP-CLAD",
  "41232942", "Perch 2026",       "Pirfenidone",                                  "Placebo",                          "Primary trial report",         "European pirfenidone BOS trial",
  "41935548", "Chambers 2026",    "Mesenchymal stromal cells (ASSIST-CLAD)",      "Placebo",                          "Primary trial report",         "ASSIST-CLAD")

rct <- an |> dplyr::filter(study_design == "rct")
# The pmid set is the contract with the pipeline. If the cohort gains or loses a trial and this table
# is not updated, fail here rather than print a table that silently omits or invents a row.
stopifnot(setequal(as.character(rct$pmid), hand$pmid))

d <- hand |>
  dplyr::left_join(rct |> dplyr::mutate(pmid = as.character(pmid)) |>
                     dplyr::select(pmid, year, sample_n_ab, intervention_intent),
                   by = "pmid") |>
  dplyr::mutate(
    Intent = factor(dplyr::case_when(intervention_intent == "treat_clad"   ~ "Treatment of established CLAD",
                                     intervention_intent == "prevent_clad" ~ "Prevention",
                                     TRUE                                  ~ "No therapeutic intent"),
                    levels = c("Treatment of established CLAD", "Prevention", "No therapeutic intent")),
    Randomized = ifelse(is.na(sample_n_ab), "Not stated in abstract", as.character(sample_n_ab))) |>
  dplyr::arrange(Intent, dplyr::desc(year))

# Reports vs trials, counted from trial_group rather than asserted in prose.
n_reports    <- nrow(d)
n_trials     <- dplyr::n_distinct(d$trial_group)
n_dup        <- n_reports - n_trials
treat        <- d |> dplyr::filter(Intent == "Treatment of established CLAD")
n_treat_rep  <- nrow(treat)
n_treat_tr   <- dplyr::n_distinct(treat$trial_group)
n_treat_pbo  <- treat |> dplyr::distinct(trial_group, .keep_all = TRUE) |>
                  dplyr::filter(comparator == "Placebo") |> nrow()

# Counts the prose needs, written beside the table rather than recomputed there: the reports-versus-trials
# distinction is exactly what prose gets wrong, so _setup.R must read the number, not derive its own.
readr::write_csv(tibble::tibble(
  n_reports = n_reports, n_trials = n_trials, n_dup = n_dup,
  n_treat_reports = n_treat_rep, n_treat_trials = n_treat_tr, n_treat_placebo = n_treat_pbo),
  file.path(dir_tables, "_trials_detail_stats.csv"))

out <- d |> dplyr::transmute(
  Intent,
  Trial = label,
  Intervention = intervention,
  Comparator = comparator,
  Randomized,
  `Report type` = report)

save_df_tbl(out, "T_trials_detail", group_col = "Intent", landscape = TRUE,
  caption = "Randomized trials in the analyzable cohort: intervention, comparator and report type",
  footer = sprintf(paste0(
    "All %d randomized trial reports in the analyzable cohort, grouped by intent and ordered by year within ",
    "each group. Intervention, comparator, report type and the grouping of reports to trials were extracted ",
    "by hand from the title and abstract of each record by one author and checked against the abstract by a ",
    "second, independently of the language-model pipeline used for the covariate panel; year, number ",
    "randomized and intent are taken from the analysis frame. Rows are trial REPORTS, not distinct ",
    "trials: %d of the %d reports are secondary, post hoc, pharmacokinetic, mechanistic or long-term analyses ",
    "of a trial whose primary report is elsewhere in this table or outside the audit population, so the %d ",
    "reports correspond to %d distinct randomized trials. Trial protocol papers report no results, and trials ",
    "that enrol established CLAD and analyse lung function have CLAD as their population rather than their ",
    "outcome; both are outside the audit population and do not appear here. Of the %d reports addressing established ",
    "CLAD (%d distinct trials), %d were placebo-controlled; the remainder compared against standard of care ",
    "alone. Number randomized is as stated in the abstract. *Abbreviations:* ALN-RSV01, small interfering RNA ",
    "targeting respiratory syncytial virus; BOS, bronchiolitis obliterans syndrome; CLAD, chronic lung ",
    "allograft dysfunction; CMV, cytomegalovirus; CNI, calcineurin inhibitor; ECP, extracorporeal ",
    "photopheresis; L-CsA, liposomal ciclosporin A; MMF, mycophenolate mofetil; RATG, rabbit antithymocyte ",
    "globulin."),
    n_reports, n_dup, n_reports, n_reports, n_trials,
    n_treat_rep, n_treat_tr, n_treat_pbo))

message(sprintf("16 complete: %d trial reports -> %d distinct trials (%d duplicate reports) | established CLAD: %d reports, %d trials, %d placebo-controlled.",
                n_reports, n_trials, n_dup, n_treat_rep, n_treat_tr, n_treat_pbo))
