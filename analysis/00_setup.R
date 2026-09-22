# 00_setup.R
# -----------------------------------------------------------------------
# Shared setup for the CLAD reporting-audit analysis scripts.
# Source this at the top of every analysis script.
#
# Conventions follow the PPFE / ALAD house style: gtsummary tables -> docx/rds/csv,
# linedraw figures + Okabe-Ito semantic palettes + companion legend .md, dual PDF/PNG
# export, hardcoded project_root (no here::here), native pipe. Data come from the
# Python pipeline: data/analysis_frame.csv (one row per paper) + data/panel_dict.csv
# (the 37-item panel, single-sourced from panel.py). Rebuild them with
#   uv run python -m clad_audit.build_frame
# -----------------------------------------------------------------------

suppressPackageStartupMessages({
  library(tidyverse)
  library(gtsummary)
  library(flextable)
  library(broom)
  library(viridis)
  library(scales)
  library(patchwork)
})

# Located by walking up from the working directory to the renv.lock at the repository root, so the
# pipeline runs from any subdirectory and on any machine. It was an absolute path to one OneDrive
# folder, which meant nothing here ran anywhere else.
project_root <- local({
  d <- normalizePath(getwd(), "/")
  while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d)
  if (!file.exists(file.path(d, "renv.lock")))
    stop("cannot locate the repository root: no renv.lock at or above ", getwd(), call. = FALSE)
  d
})
dir_analysis <- file.path(project_root, "analysis")
dir_figures  <- file.path(dir_analysis, "figures")
dir_tables   <- file.path(dir_analysis, "tables")
dir.create(dir_figures, recursive = TRUE, showWarnings = FALSE)
dir.create(dir_tables,  recursive = TRUE, showWarnings = FALSE)

# Recommended column weights, computed once at the table rather than per document. Vendored from the
# house style so that analysis/ depends on nothing outside this repository — it was sourcing the whole
# house-style file for this one function, which made the pipeline unrunnable without ~/.dotfiles.
source(file.path(dir_analysis, "col_widths.R"))

# -----------------------------------------------------------------------
# Data
# -----------------------------------------------------------------------
# af : all extracted papers (Phase-1, 45%-coverage set). One row per paper.
#      score_<key> in {not, partial, full, na, missing}; adj_<key> logical
#      (covariate entered in the primary multivariable CLAD model).
# an : ANALYZABLE cohort = CLAD an analysed outcome (outcome_role primary|secondary).
#      The primary completeness denominator; descriptor/exclude are dropped.
# panel : the 37-item dictionary (key, tier, label, min_set, recommended, conditional).
#
# NB (read before interpreting): these are Phase-1 numbers on the fetched 45% (OA/ISTEX/
# recent-skewed, JHLT under-represented) and are NOT yet kappa-validated. Table-based items
# (HLA/CMV/ACR) may be under-scored from PDFs -> "not reported" possibly inflated. Lead
# reporting with per-item %not, not the min-set composite. See docs/methods.md.
af    <- read_csv(file.path(project_root, "data/analysis_frame.csv"), show_col_types = FALSE)
panel <- read_csv(file.path(project_root, "data/panel_dict.csv"),     show_col_types = FALSE)

tier_labels <- c(A = "Case-mix / context", B = "Core immunological",
                 C = "Non-alloimmune second hits", D = "Novel / emerging",
                 E = "Outcome ascertainment")

# Factor orders for tables / figures
af <- af |>
  mutate(
    outcome_role = factor(outcome_role, levels = c("primary", "secondary", "descriptor", "exclude")),
    study_design = factor(study_design, levels = c("rct", "prospective_cohort", "retrospective_cohort",
                                                   "registry", "cross_sectional", "other")),
    era          = factor(era, levels = c("pre", "post"), labels = c("Pre-2019", "2019+")),
    source_format = factor(source_format, levels = c("xml", "pdf", "txt"))
  )
panel <- panel |>
  mutate(tier_label = factor(tier_labels[tier], levels = unname(tier_labels)),
         label = fct_reorder(label, match(tier, names(tier_labels))))

an <- af |> filter(outcome_role %in% c("primary", "secondary"))
n_preclinical <- 0
if ("clinical" %in% names(af)) {           # restrict the audit to human clinical studies
  n_preclinical <- sum(an$clinical %in% FALSE)
  an <- an |> filter(!(clinical %in% FALSE))
}
# Eligibility on STUDY STRUCTURE (schema fields, not a post-hoc PMID list). The audit population is patient-level
# studies that estimate an exposure->CLAD effect, i.e. where the immunological covariate panel is a relevant
# confounder set. We key on the thing the audit measures, NOT on a translational-vs-clinical TOPIC label:
#   - clinical_cohort / trial / registry  -> always eligible (a covariate panel is expected by design)
#   - mechanistic_translational           -> eligible IFF it has an exposure->CLAD analysis (exposure_measure set).
#       This KEEPS prognostic biomarker cohorts (dd-cfDNA, DSA, CXCL9/10, gene-expression): a marker->CLAD study
#       that omits ACR/CMV/induction is exactly the reported-vs-adjusted gap we audit. It DROPS only pure
#       cross-sectional immunophenotyping snapshots with no exposure->outcome estimate (panel undefined there).
#   - methods_or_review / case_report_series -> always excluded (not primary covariate-reporting studies).
# (An earlier TOPIC-based gate kept only clinical_cohort/trial/registry; it was over-broad — dropped 145 studies,
# 125 of which define an exposure->CLAD effect, incl. every dd-cfDNA/DSA cohort. See docs/methods.md §3/§6.)
n_noncohort <- 0
n_snapshot  <- 0
if ("study_type" %in% names(af)) {
  has_exposure     <- !is.na(an$exposure_measure) & trimws(as.character(an$exposure_measure)) != ""
  drop_review_case <- an$study_type %in% c("methods_or_review", "case_report_series")
  drop_snapshot    <- (an$study_type %in% "mechanistic_translational") & !has_exposure
  eligible         <- !(drop_review_case | drop_snapshot)
  n_noncohort <- sum(drop_review_case)          # reviews / methods / case reports
  n_snapshot  <- sum(drop_snapshot)             # mechanistic snapshots with no exposure->CLAD estimate
  an <- an |> filter(eligible)
}
# Recipients must be LUNG transplant recipients. The search pairs a lung-transplant term with a CLAD/BOS
# term anywhere in the record, so studies of BOS after allogeneic haematopoietic cell transplantation —
# a manifestation of chronic GVHD, not of lung allograft rejection — matched and passed every downstream
# gate, none of which asked which organ was transplanted. Surfaced by human validation coding (a coder
# flagged ALLOZITHRO while scoring intervention intent), then adjudicated once against title and abstract.
# The rule is that the ANALYSED POPULATION CONTAINS NO LUNG TRANSPLANT RECIPIENTS, so studies comparing
# both populations, and studies of lung transplantation FOR post-HSCT lung disease, are kept.
# Deterministic and auditable: the decisions live in data/exclusions_fulltext.csv (tracked), not in code.
#
# The same file also carries `protocol_no_results`: trial protocol and design papers, which report a
# planned analysis and no results. They are ineligible under the stated audit population — a study
# "estimating an exposure-to-CLAD effect" — because they estimate nothing, and scoring them for
# reporting completeness measures the absence of results rather than the absence of reporting. Two of the
# three scored 0 and 1 of the minimum set, pulling completeness down; the third scored 4, because a
# protocol describes its planned regimen in detail. They were noise in both directions.
n_notlung <- 0
n_protocol <- 0
.excl_path <- file.path(project_root, "data/exclusions_fulltext.csv")
if (file.exists(.excl_path)) {
  .excl <- read_csv(.excl_path, show_col_types = FALSE) |> mutate(pmid = as.character(pmid))
  .in_coh <- .excl |> filter(pmid %in% as.character(an$pmid))
  n_notlung  <- sum(.in_coh$reason == "not_lung_transplant")
  n_protocol <- sum(.in_coh$reason == "protocol_no_results")
  an <- an |> filter(!(as.character(pmid) %in% .excl$pmid))
}

# Protocol papers were found by hand (a co-author asked whether they belonged, 2026-08-31), which is the
# same accident that produced the organ-exclusion list. Screen for them on every build so the answer is a
# result rather than an assumption. Deliberately broad: a hit stops the build for a human decision, and a
# false positive costs one adjudication while a miss costs a study that had no results being scored as a
# study that reported nothing. The four known false positives are results papers that merely discuss a
# treatment protocol or the design of future trials, and are listed so the screen stays silent until the
# corpus actually changes.
# Both screens below read the ABSTRACT text, which the public export strips: PubMed abstracts are
# publisher-copyright and NLM grants no redistribution right (tools/export_public.py). They are
# integrity checks on the WORKING tree, not analysis — nothing downstream depends on their output —
# so where the column is absent they announce themselves and stand down rather than halting a
# reproduction run. Added 2026-09-02 after the exported tree died on "objet 'abstract' introuvable":
# the organ screen had made export_public.py's "the analysis never reads it" false on 2026-08-16 and
# nobody noticed, because the export was never run end to end again.
.has_abstract <- function(df) "abstract" %in% names(df)

.proto_ok <- c("31909902", "41058980", "41032890", "40453071")
if (file.exists(file.path(project_root, "data/corpus.csv"))) {
  .pt <- read_csv(file.path(project_root, "data/corpus.csv"), show_col_types = FALSE) |>
    filter(as.character(pmid) %in% as.character(an$pmid))
  .pti <- tolower(coalesce(.pt$title, "")); .ptj <- tolower(coalesce(.pt$journal, ""))
  .ptb <- if (.has_abstract(.pt)) tolower(coalesce(.pt$abstract, "")) else rep("", nrow(.pt))
  if (!.has_abstract(.pt))
    message("00_setup: protocol screen runs on title and journal only (no abstract column in this tree).")
  .phit <- grepl("protocol for|study protocol|: *design of|design and rationale|rationale and design|trial design|^protocol", .pti) |
           grepl("^trials$|res protoc", .ptj) |
           grepl("will be randomi[sz]|will be enrolled|will be recruited|patients will be|we will (assess|compare|evaluate|enrol)|end-?points? will be|is currently recruiting", .ptb)
  .pbad <- setdiff(as.character(.pt$pmid[.phit]), .proto_ok)
  if (length(.pbad))
    stop(sprintf(paste0("00_setup: protocol screen — %d analysed stud%s read as a trial protocol or design ",
                        "paper: %s. Adjudicate each against the title and abstract; if it reports no results, ",
                        "add it to data/exclusions_fulltext.csv with reason protocol_no_results, otherwise add ",
                        "it to .proto_ok in this file."),
                 length(.pbad), if (length(.pbad) == 1) "y" else "ies",
                 paste(.pbad, collapse = ", ")), call. = FALSE)
}

# The exclusion list above is ten adjudicated identifiers, and it was assembled by ACCIDENT — a coder
# flagged ALLOZITHRO while scoring something else. Nothing ever screened the cohort systematically, so
# "there are no haematopoietic-transplant studies left" was an assumption, not a result. This makes it a
# result, on every build.
#
# The rule is the one stated above: a study is contaminating only if its analysed population contains NO
# lung transplant recipients. So the screen flags a study that talks about haematopoietic transplantation
# or GVHD while never mentioning lung transplantation at all. Studies covering both populations, and
# studies of lung transplantation FOR post-HSCT lung disease, mention lung transplantation and pass.
#
# Currently flags 0 of 1,060. It stops the build rather than warning, because a new hit needs a human
# decision recorded in data/exclusions_fulltext.csv, not a message nobody reads.
.hct_re <- paste0("(allogeneic|allogenic|haematopoietic|hematopoietic)|\\bHSCT\\b|\\bHCT\\b|",
                  "bone marrow transplant|stem cell transplant|graft.versus.host|\\bGVHD\\b")
.ltx_re <- paste0("lung transplant|lung allograft|pulmonary transplant|bilateral lung|single lung|",
                  "lung recipient|heart.lung transplant")
.corpus_path <- file.path(project_root, "data/corpus.csv")
n_hct_mention <- NA_integer_
if (file.exists(.corpus_path)) {
  .txt <- read_csv(.corpus_path, show_col_types = FALSE) |>
    filter(as.character(pmid) %in% as.character(an$pmid))
  if (!.has_abstract(.txt))
    message("00_setup: organ screen runs on titles only (no abstract column in this tree).")
  .txt <- .txt |> mutate(.t = if (.has_abstract(.txt)) paste(title, abstract) else title)
  n_hct_mention <- sum(grepl(.hct_re, .txt$.t, ignore.case = TRUE))
  .bad <- .txt |> filter(grepl(.hct_re, .t, ignore.case = TRUE),
                         !grepl(.ltx_re, .t, ignore.case = TRUE))
  if (nrow(.bad))
    stop(sprintf(paste0("00_setup: organ screen — %d analysed stud%s haematopoietic transplantation ",
                        "or GVHD and never mention lung transplantation: %s. Adjudicate each against the ",
                        "title and abstract and, if the analysed population contains no lung transplant ",
                        "recipients, add it to data/exclusions_fulltext.csv with a reason."),
                 nrow(.bad), if (nrow(.bad) == 1) "y mentions" else "ies mention",
                 paste(.bad$pmid, collapse = ", ")), call. = FALSE)
}

min_set_keys <- panel |> filter(min_set) |> pull(key)

# Long score frame (one row per paper × item), labelled + tiered.
# `applicable` = scored not/partial/full (drops na = conditional-inapplicable and
# missing = model returned nothing); this is the completeness denominator.
scores_long <- function(d) {
  d |>
    select(pmid, outcome_role, study_design, era, source_format, tier_src = tier,
           starts_with("score_")) |>
    pivot_longer(starts_with("score_"), names_to = "key", values_to = "score",
                 names_prefix = "score_") |>
    left_join(panel, by = "key") |>
    mutate(score = factor(score, levels = c("not", "partial", "full", "na", "missing")),
           applicable = score %in% c("not", "partial", "full"))
}

# -----------------------------------------------------------------------
# Helpers (ported from the PPFE house style)
# -----------------------------------------------------------------------
med_iqr <- function(x) { x <- x[!is.na(x)]; sprintf("%.1f [%.1f–%.1f]", median(x), quantile(x, .25), quantile(x, .75)) }
# Thousands separator for every study count that reaches a caption, legend or prose line. Defined here,
# where both the analysis scripts and publication/_setup.R can see it: it used to be defined twice, and
# the counts formatted with a bare %d rendered "1063" beside a "1,063" written by the other copy.
cm <- function(x) format(x, big.mark = ",", trim = TRUE)
n_pct   <- function(x) sprintf("%d (%.0f%%)", sum(x, na.rm = TRUE), mean(x, na.rm = TRUE) * 100)
fmt_ci  <- function(est, lo, hi, d = 2) sprintf(paste0("%.", d, "f (%.", d, "f, %.", d, "f)"), est, lo, hi)
fmt_p   <- function(p) ifelse(p < .001, "<0.001", formatC(p, format = "f", digits = 3))
fmt_star<- function(p) case_when(p < .001 ~ "***", p < .01 ~ "**", p < .05 ~ "*", TRUE ~ "")
# Whole-percent display, but NEVER round a non-zero share down to "0%" or a non-total up to "100%".
# In a reporting audit those two cells are read as universals: "0% not reported" states that every study
# reports the item, when 3 of 1,072 studies do not define CLAD at all (0.28%) — which is exactly the
# reading that a 0-of-6 minimum-set study contradicts. `<1%` / `>99%` keep the claim honest at the same
# width. Exact 0 and exact 1 still print as "0%" / "100%".
pct <- function(x) {
  out <- sprintf("%.0f%%", 100 * x)
  small <- !is.na(x) & x > 0 & 100 * x < 0.5
  large <- !is.na(x) & x < 1 & 100 * x > 99.5
  out[small] <- "<1%"
  out[large] <- ">99%"
  out
}

# Footer = single source of a table's note. It drives BOTH the .docx (flextable footer, markdown emphasis
# flattened) AND the rendered report, via a `<name>_footer.md` sidecar that show_csv/show_gts read by default
# (mirrors the figure `<name>_legend.md` sidecars). Authored ONCE here, at the table, never re-typed in the .Rmd.
.footer_plain <- function(x) gsub("\\*(\\S[^*]*?\\S|\\S)\\*", "\\1", x)   # drop *emphasis* pairs for docx; keep lone "* " markers
.write_footer  <- function(name, footer) {
  p <- file.path(dir_tables, paste0(name, "_footer.md"))
  if (is.null(footer)) { if (file.exists(p)) file.remove(p); return(invisible()) }
  writeLines(paste(footer, collapse = " "), p)                # raw markdown → report renders it (gt::md / pandoc)
}

# Display metadata sidecar, written next to <name>_footer.md and read by show_table(). Grouping and
# column weights belong to the TABLE, not to the document showing it: 15 of these tables appear in both
# the manuscript supplement and the analysis report, and specifying display per document is how one copy
# came to group by tier while the other did not, and how two copies of the same table drifted to
# different widths. Authored once here, at the table.
#   group_col  : column rendered as section header rows instead of a repeated column
#   col_widths : relative weights; derived from content unless given
#   landscape  : rotate the page (PDF)
.write_display <- function(name, group_col = NULL, col_widths = NULL, landscape = FALSE) {
  p <- file.path(dir_tables, paste0(name, "_display.dcf"))
  f <- list()
  if (!is.null(group_col)) f$group_col <- group_col
  if (!is.null(col_widths)) f$col_widths <- paste(col_widths, collapse = ",")
  if (isTRUE(landscape)) f$landscape <- "TRUE"
  if (!length(f)) { if (file.exists(p)) file.remove(p); return(invisible()) }
  write.dcf(as.data.frame(f, stringsAsFactors = FALSE), p)
  invisible()
}

# Save a gtsummary table as .docx (flextable) + .rds + .csv (clean display tibble) + footer sidecar.
# gtsummary takes derived widths like any other table: tex_tblr renders the **header** / __label__ markup
# its cells carry, so the width path no longer costs the bold.
save_tbl <- function(tbl, name, footer = NULL, group_col = NULL, landscape = FALSE, col_widths = NULL) {
  ft <- as_flex_table(tbl)
  if (!is.null(footer)) ft <- flextable::add_footer_lines(ft, .footer_plain(footer))
  flextable::save_as_docx(ft, path = file.path(dir_tables, paste0(name, ".docx")))
  saveRDS(tbl, file.path(dir_tables, paste0(name, ".rds")))
  df <- gtsummary::as_tibble(tbl)
  names(df) <- gsub("\\*\\*", "", names(df))          # strip markdown bold from headers
  readr::write_csv(df, file.path(dir_tables, paste0(name, ".csv")))
  .write_footer(name, footer)
  if (is.null(col_widths)) col_widths <- auto_col_widths(as.data.frame(df), group_col)
  .write_display(name, group_col = group_col, col_widths = col_widths, landscape = landscape)
  invisible(name)
}

# Save a plain results data frame as a formatted .docx (flextable) + .csv + footer sidecar.
# col_widths defaults to weights derived from the table's own content (auto_col_widths), so a caller
# never has to guess-render-correct; pass a vector to override.
save_df_tbl <- function(df, name, caption = NULL, footer = NULL, group_col = NULL, landscape = FALSE,
                        col_widths = NULL) {
  ft <- flextable::flextable(df) |>
    flextable::bold(part = "header") |>
    flextable::valign(valign = "top", part = "all") |>
    flextable::set_table_properties(layout = "autofit")
  if (!is.null(caption)) ft <- flextable::set_caption(ft, caption)
  if (!is.null(footer))  ft <- flextable::add_footer_lines(ft, .footer_plain(footer))
  flextable::save_as_docx(ft, path = file.path(dir_tables, paste0(name, ".docx")))
  readr::write_csv(df, file.path(dir_tables, paste0(name, ".csv")))
  .write_footer(name, footer)
  if (is.null(col_widths)) col_widths <- auto_col_widths(as.data.frame(df), group_col)
  .write_display(name, group_col = group_col, col_widths = col_widths, landscape = landscape)
  invisible(name)
}

# Save a ggplot/patchwork as both PDF (vector, cairo) and PNG (300 dpi)
save_fig <- function(stem, plot, width, height) {
  ggplot2::ggsave(file.path(dir_figures, paste0(stem, ".pdf")), plot, width = width, height = height,
                  device = grDevices::cairo_pdf)
  ggplot2::ggsave(file.path(dir_figures, paste0(stem, ".png")), plot, width = width, height = height, dpi = 300)
  invisible(stem)
}
write_legend <- function(name, txt) writeLines(txt, file.path(dir_figures, paste0(name, "_legend.md")))

# -----------------------------------------------------------------------
# Figure theme + semantic palettes (edit colours in theme_clad.R)
# -----------------------------------------------------------------------
source(file.path(dir_analysis, "theme_clad.R"))
theme_gtsummary_compact(set_theme = TRUE)

message(sprintf(paste0("00_setup.R complete. Papers: %d total | %d analyzable | panel items: %d ",
                       "(dropped: %d preclinical, %d review/methods/case, %d mechanistic snapshots w/o exposure)."),
                nrow(af), nrow(an), nrow(panel), n_preclinical, n_noncohort, n_snapshot))
