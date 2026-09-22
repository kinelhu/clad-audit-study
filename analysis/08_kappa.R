# 08_kappa.R
# -----------------------------------------------------------------------
# Kappa validation: LLM vs human (and human vs human) agreement on the item scores
# and the outcome-role tag, on the blinded subset from `uv run python -m clad_audit.kappa_export`.
# Weighted (squared) kappa per item over the ordinal not<partial<full; Cohen kappa on outcome_role.
# Runs at the END (after coders fill the sheets); no-ops gracefully until then.
# Output: T_kappa (per-item κ), T_kappa_classifier (gate b), a source-format table-extraction check, and
# _kappa_stats.csv, which the manuscript and report read so no κ is retyped in prose.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))
suppressPackageStartupMessages({ library(irr); library(readxl) })

kdir <- file.path(project_root, "data/kappa")
# One workbook per coder: items|papers|intent tabs. Prefer "<coder>_filled.xlsx" — coders keep the blank
# pristine and work on a copy, so the export can be re-run without destroying work in progress.
wb <- function(c) {
  f <- file.path(kdir, sprintf("coder_%s_filled.xlsx", c))
  if (file.exists(f)) f else file.path(kdir, sprintf("coder_%s.xlsx", c))
}
# A second coder is OPTIONAL. With one expert this is agreement against a reference standard rather than
# inter-rater reliability, so there is no A-vs-B ceiling to report; everything else is unchanged.
# Coding arrives TAB BY TAB (the intent tab is quick, the item tab is the long haul), so each axis is
# scored as soon as its own tab is filled rather than waiting for the whole workbook.
has_coding <- function(c, sheet = "items", col = "human_score") {
  f <- wb(c); if (!file.exists(f)) return(FALSE)
  d <- try(suppressMessages(read_excel(f, sheet = sheet)), silent = TRUE)
  if (inherits(d, "try-error") || !col %in% names(d)) return(FALSE)
  any(!is.na(d[[col]]) & trimws(as.character(d[[col]])) != "")
}
# The sample was drawn BEFORE the current eligibility gates; validate on the cohort actually audited, so a
# study later excluded cannot count for or against extraction accuracy. Report what this drops, because
# silently shrinking a validation set to improve its result would be exactly the wrong move.
in_cohort <- function(d) {
  n0 <- length(unique(d$pmid))
  d <- d |> filter(as.character(pmid) %in% as.character(an$pmid))
  n1 <- length(unique(d$pmid))
  if (n1 < n0) message(sprintf("08_kappa: %d sampled paper(s) dropped — no longer in the analyzable cohort.", n0 - n1))
  d
}
coders     <- c("A", "B")[vapply(c("A", "B"), function(c) has_coding(c), logical(1))]
did_items  <- length(coders) > 0
did_papers <- has_coding("A", "papers", "human_outcome_role")
did_intent <- has_coding("A", "intent", "human_intent") &&
              file.exists(file.path(kdir, "kappa_key_intent.csv"))
coded      <- did_items || did_papers || did_intent
# hard-reject out-of-list values (belt-and-suspenders: the xlsx dropdowns don't survive import into Numbers)
chk <- function(x, ok, what) {
  bad <- setdiff(unique(stats::na.omit(x)), c(ok, ""))
  if (length(bad)) stop(sprintf("08_kappa: invalid %s value(s): %s", what, paste(bad, collapse = ", ")))
}
if (!coded) {
  message("08_kappa: no completed coding sheets yet — run kappa_export, fill ",
          "data/kappa/coder_A[_filled].xlsx (items/papers/intent tabs), then re-run. Skipping.")
} else {
  # ---- assemble per (pmid,item) ratings: llm + one column per coder --------
  lev <- c("not", "partial", "full")                       # ordinal; na/missing dropped
  as_ord <- function(x) factor(x, levels = lev) |> as.integer()   # not=1,partial=2,full=3
  read_items <- function(c) read_excel(wb(c), sheet = "items") |>
    transmute(pmid = as.character(pmid), item_key = as.character(item_key), human_score = as.character(human_score))
  per_item <- NULL
if (did_items) {
  key <- read_csv(file.path(kdir, "kappa_key.csv"), show_col_types = FALSE) |>
    mutate(pmid = as.character(pmid), item_key = as.character(item_key))
  ratings <- key |> rename(llm = llm_score) |> in_cohort()
  for (cd in coders) {
    d <- read_items(cd)
    chk(d$human_score, c(lev, "na"), sprintf("human_score (coder %s)", cd))
    ratings <- ratings |>
      left_join(d |> select(pmid, item_key, !!cd := human_score), by = c("pmid", "item_key"))
  }
  ratings <- ratings |> mutate(across(all_of(c("llm", coders)), \(x) as_ord(x)))

  wkappa <- function(x, y) {                              # weighted (squared) κ on complete ordinal pairs
    d <- na.omit(data.frame(x, y))
    if (nrow(d) < 10 || length(unique(c(d$x, d$y))) < 2) return(NA_real_)
    irr::kappa2(d, weight = "squared")$value
  }

  # ---- per-item κ (LLM vs human A, LLM vs B, A vs B) ------------------------
  per_item <- ratings |>
    group_by(item_key) |>
    summarise(n = sum(!is.na(llm) & !is.na(.data[[coders[1]]])),
              across(all_of(coders), \(x) wkappa(llm, x), .names = "k_llm_{.col}"),
              k_ceiling = if (length(coders) > 1) wkappa(.data[[coders[1]]], .data[[coders[2]]]) else NA_real_,
              .groups = "drop") |>
    left_join(panel |> select(item_key = key, label, tier_label, min_set), by = "item_key") |>
    mutate(k_llm_human = rowMeans(across(starts_with("k_llm_")), na.rm = TRUE),
           flag = if_else(k_llm_human < 0.6, "⚠ revise", "")) |>
    arrange(k_llm_human)

  one <- length(coders) < 2
  tab <- per_item |>
    transmute(Tier = tier_label, Item = ifelse(min_set, paste0(label, " ★"), as.character(label)),
              N = n, `κ LLM–expert` = round(k_llm_human, 2),
              `κ A–B (ceiling)` = round(k_ceiling, 2), Flag = flag)
  if (one) tab <- tab |> select(-`κ A–B (ceiling)`)
  save_df_tbl(tab, "T_kappa",
              caption = paste0("Weighted-κ agreement between the LLM extraction and ",
                               if (one) "an expert reference standard" else "human coders",
                               " (blinded subset). ★ minimum set."),
              footer = paste0("Weighted (squared) κ over the ordinal not<partial<full; na and missing dropped. ",
                "The coder scored from the full text blinded to the model's answers. κ < 0.6 flags the item for ",
                "anchor revision and re-extraction. ",
                if (one) paste0("A single expert coded the subset, so agreement is against a reference standard ",
                                "rather than between raters, and no inter-human ceiling is available: read a low ",
                                "κ as either model error or an item that is inherently ambiguous.")
                else "κ A–B is the inter-human ceiling and bounds what agreement is attainable.",
                " *Abbreviations:* ACR, acute cellular rejection; AMR, antibody-mediated rejection; CMV, ",
                "cytomegalovirus; D/R, donor/recipient; HLA, human leucocyte antigen; IS, immunosuppression; ",
                "κ, Cohen or weighted kappa."))
}

  # ---- paper-level agreement (Cohen κ, nominal): outcome-role + study-design ----
  ckappa <- function(d, llm_col, hum_col) {                # Cohen κ on complete nominal pairs
    d <- d |> filter(!is.na(.data[[hum_col]]), .data[[hum_col]] != "")
    # A part-coded tab is normal while coding is in progress; say so rather than returning a bare NA that
    # reads like a failure.
    if (nrow(d) < 10) {
      message(sprintf("08_kappa: %s has %d coded row(s) — need 10 for a κ.", hum_col, nrow(d)))
      return(NA_real_)
    }
    irr::kappa2(d |> select(all_of(c(llm_col, hum_col))))$value
  }
  role_kappa <- NA_real_; design_kappa <- NA_real_
if (did_papers) {
  kp <- read_csv(file.path(kdir, "kappa_key_paper.csv"), show_col_types = FALSE) |> mutate(pmid = as.character(pmid))
  pa <- read_excel(wb("A"), sheet = "papers") |>
    transmute(pmid = as.character(pmid), roleA = as.character(human_outcome_role),
              designA = as.character(human_study_design))
  chk(pa$roleA,   c("primary", "secondary", "descriptor", "exclude"), "human_outcome_role")
  chk(pa$designA, c("rct", "prospective_cohort", "retrospective_cohort", "registry", "cross_sectional", "other"),
      "human_study_design")
  role_df      <- kp |> left_join(pa, by = "pmid") |> in_cohort()
  role_kappa   <- ckappa(role_df, "outcome_role_llm", "roleA")
  design_kappa <- ckappa(role_df, "study_design_llm", "designA")
}

  # ---- title/abstract CLASSIFIER agreement (gate b) --------------------------------------------
  # A separate sheet and a separate sample: this validates classify.py, which sets the eligibility
  # denominator and the interventional count, and which the full-text κ above does not touch. NOT filtered
  # to the analyzable cohort — the classifier's job is to decide who enters it, so restricting to survivors
  # would only score it on the cases it already let through.
  clf <- NULL
  # Same convention as wb(): the coder works on a "_filled" copy and leaves the blank export pristine.
  clf_sheet <- file.path(kdir, "classifier_sheet_filled.xlsx")
  if (!file.exists(clf_sheet)) clf_sheet <- file.path(kdir, "classifier_sheet.xlsx")
  clf_key   <- file.path(kdir, "kappa_key_classifier.csv")
  if (file.exists(clf_sheet) && file.exists(clf_key)) {
    ca <- suppressMessages(read_excel(clf_sheet, sheet = "abstracts"))
    if (any(!is.na(ca$human_study_type) & trimws(as.character(ca$human_study_type)) != "")) {
      ca <- ca |> transmute(pmid = as.character(pmid),
                            t_h = as.character(human_study_type), i_h = as.character(human_evaluates_intervention),
                            c_h = as.character(human_clinical),   d_h = as.character(human_study_design))
      chk(ca$t_h, c("clinical_cohort", "mechanistic_translational", "registry", "trial",
                    "methods_or_review", "case_report_series"), "human_study_type")
      chk(ca$i_h, c("yes", "no"), "human_evaluates_intervention")
      chk(ca$c_h, c("yes", "no"), "human_clinical")
      chk(ca$d_h, c("rct", "prospective_cohort", "retrospective_cohort", "registry", "cross_sectional", "other"),
          "human_study_design (classifier)")
      cd <- read_csv(clf_key, show_col_types = FALSE) |> mutate(pmid = as.character(pmid)) |>
        left_join(ca, by = "pmid")
      # κ on study_type understates how well the GATE works, because eligibility composes study_type with
      # the full-text exposure field: clinical_cohort and mechanistic_translational differ as labels but
      # both survive when the study carries an exposure->CLAD estimate. Count the disagreements that would
      # actually move a study in or out of the cohort — that is the number the denominator rests on.
      .cls <- function(x) dplyr::case_when(x %in% c("clinical_cohort", "trial", "registry") ~ "in",
                                           x == "mechanistic_translational" ~ "conditional", TRUE ~ "out")
      .exp <- af |> transmute(pmid = as.character(pmid),
                              has_exp = !is.na(exposure_measure) & trimws(as.character(exposure_measure)) != "")
      .net <- cd |> left_join(.exp, by = "pmid") |>
        mutate(a = .cls(study_type_llm), b = .cls(t_h),
               # resolve "conditional" through the exposure field, exactly as the eligibility rule does
               ra = dplyr::if_else(a == "conditional", dplyr::if_else(has_exp %in% TRUE, "in", "out"), a),
               rb = dplyr::if_else(b == "conditional", dplyr::if_else(has_exp %in% TRUE, "in", "out"), b))
      clf_disagree <- sum(cd$study_type_llm != cd$t_h, na.rm = TRUE)
      clf_net      <- sum(.net$ra != .net$rb, na.rm = TRUE)

      clf <- tibble(
        field = c("study_type", "evaluates_intervention", "clinical", "study_design"),
        kappa = c(ckappa(cd, "study_type_llm", "t_h"), ckappa(cd, "evaluates_intervention_llm", "i_h"),
                  ckappa(cd, "clinical_llm", "c_h"),   ckappa(cd, "study_design_llm", "d_h")),
        n = c(sum(nzchar(cd$t_h %||% "")), sum(nzchar(cd$i_h %||% "")),
              sum(nzchar(cd$c_h %||% "")), sum(nzchar(cd$d_h %||% ""))))
      save_df_tbl(clf |> transmute(Field = field, N = n, `κ classifier–expert` = sprintf("%.2f", kappa),
                                   Flag = if_else(kappa < 0.6, "revise", "")),
                  "T_kappa_classifier",
                  caption = "Agreement between the title/abstract classifier and an expert reference standard",
                  footer = paste0("Cohen κ on a blinded stratified sample of abstracts, coded from title and ",
                    "abstract alone, which is what the classifier reads. Sampling is weighted towards the ",
                    "clinical-cohort versus mechanistic-translational boundary, the distinction the eligibility ",
                    "gate turns on, so κ here is a harder test than a proportional sample would give. study_type ",
                    "sets the analyzable denominator and evaluates_intervention is authoritative for the ",
                    "interventional count. κ below 0.60 flags the field for a prompt revision and re-classification. ",
                    "*Abbreviations:* κ, Cohen kappa."))
    }
  }

  # ---- interventional intent agreement (Cohen κ) — the weakest axis; guarded on the tab existing ----
  intent_kappa <- NA_real_
  fi <- file.path(kdir, "kappa_key_intent.csv")
  if (did_intent) {
    it <- read_excel(wb("A"), sheet = "intent") |>
      transmute(pmid = as.character(pmid), intentA = as.character(human_intent))
    chk(it$intentA, c("prevent_clad", "treat_clad", "na"), "human_intent")
    intent_df <- read_csv(fi, show_col_types = FALSE) |> mutate(pmid = as.character(pmid)) |>
      left_join(it, by = "pmid") |> in_cohort()
    intent_kappa <- ckappa(intent_df, "intervention_intent_llm", "intentA")
  }

  # No κ figure. Five bars all sitting between 0.96 and 1.00 is a table's worth of information drawn at
  # figure size; T_kappa carries it. Dropped 2026-08-14.

  # ---- table-extraction check: HLA/CMV κ by source format ------------------
  tcheck <- NULL
if (did_items) {
  sf <- read_csv(file.path(kdir, "sample_manifest.csv"), show_col_types = FALSE) |>
    transmute(pmid = as.character(pmid), source_format)
  tcheck <- ratings |> filter(item_key %in% c("hla_mismatch", "cmv_dr")) |>
    left_join(sf, by = "pmid") |>
    group_by(item_key, source_format) |>
    summarise(k_llm_A = wkappa(llm, A), n = sum(!is.na(llm) & !is.na(A)), .groups = "drop")
  save_df_tbl(tcheck |> transmute(Item = item_key, Source = source_format, N = n, `κ LLM–A` = round(k_llm_A, 2)),
              "T_kappa_source_check",
              caption = "Table-extraction check: HLA / CMV agreement by source format (XML vs PDF).",
              footer = paste0("Weighted (squared) κ between the LLM extraction and coder A, for the two items ",
                "carried mainly in baseline tables, split by the text layer the extraction read. Agreement that ",
                "falls on PDF-sourced text would indicate that not-reported partly reflects table-extraction ",
                "failure rather than absence from the paper. Denominators are the sampled papers with both ",
                "scores present. *Abbreviations:* CMV, cytomegalovirus; HLA, human leucocyte antigen; LLM, large ",
                "language model; PDF, portable document format; XML, extensible markup language; κ, weighted kappa."))
}

  # Persist the headline values so the manuscript and report can compute them rather than retype them
  # (publication/_setup.R reads this). Not an exhibit: leading underscore keeps it out of the table set.
  if (did_items) {
    agree <- ratings |> filter(!is.na(llm), !is.na(.data[[coders[1]]]))
    readr::write_csv(tibble::tibble(
      n_papers   = length(unique(agree$pmid)),
      n_cells    = nrow(agree),
      k_items    = mean(per_item$k_llm_human, na.rm = TRUE),
      agreement  = mean(agree$llm == agree[[coders[1]]]),
      # STRUCTURE of the disagreements, not just their number. Two things are claimed about them in the
      # supplement and they must be computed, because both changed when the coding file was corrected:
      # whether any disagreement spans more than one ordinal step, and how many cross the not-reported
      # boundary rather than merely differing on granularity. The earlier file supported "none crossed";
      # the corrected one does not.
      n_disagree  = sum(agree$llm != agree[[coders[1]]]),
      n_twostep   = sum(abs(agree$llm - agree[[coders[1]]]) >= 2),
      n_cross_zero = sum(agree$llm != agree[[coders[1]]] &
                         pmin(agree$llm, agree[[coders[1]]]) == 1),   # 1 == "not" on the 1/2/3 ordinal
      worst_disagree_item = { .lb <- setNames(panel$label, panel$key)
                              .t <- table(.lb[agree$item_key[agree$llm != agree[[coders[1]]]]])
                              if (length(.t)) names(.t)[which.max(.t)] else NA_character_ },
      k_role     = role_kappa,
      k_design   = design_kappa,
      k_intent   = intent_kappa,
      worst_item = per_item$label[which.min(per_item$k_llm_human)],
      worst_k    = min(per_item$k_llm_human, na.rm = TRUE),
      n_coders   = length(coders),
      # Gate (b). NA until the classifier sheet is coded, so a document can test for it rather than
      # carry a claim that is not yet true.
      clf_n         = if (is.null(clf)) NA_integer_ else max(clf$n),
      clf_type      = if (is.null(clf)) NA_real_ else clf$kappa[clf$field == "study_type"],
      clf_interv    = if (is.null(clf)) NA_real_ else clf$kappa[clf$field == "evaluates_intervention"],
      clf_clinical  = if (is.null(clf)) NA_real_ else clf$kappa[clf$field == "clinical"],
      clf_design    = if (is.null(clf)) NA_real_ else clf$kappa[clf$field == "study_design"],
      clf_min       = if (is.null(clf)) NA_real_ else min(clf$kappa, na.rm = TRUE),
      clf_disagree  = if (is.null(clf)) NA_integer_ else clf_disagree,
      clf_net       = if (is.null(clf)) NA_integer_ else clf_net),
      file.path(dir_tables, "_kappa_stats.csv"))
  }

  message(sprintf(paste0("08_kappa: %s | items %s | role %s | design %s | intent %s"),
                  paste(length(coders), "coder(s):", paste(coders, collapse = "+")),
                  if (did_items) sprintf("mean κ %.2f, %d flagged (<0.6)",
                                         mean(per_item$k_llm_human, na.rm = TRUE),
                                         sum(per_item$k_llm_human < 0.6, na.rm = TRUE)) else "not coded",
                  if (did_papers) sprintf("κ %.2f", role_kappa) else "not coded",
                  if (did_papers) sprintf("κ %.2f", design_kappa) else "not coded",
                  if (did_intent) sprintf("κ %.2f", intent_kappa) else "not coded"))
  message(if (is.null(clf)) "08_kappa: classifier sheet not coded yet (gate b outstanding)."
          else sprintf("08_kappa: classifier | %s",
                       paste(sprintf("%s %.2f", clf$field, clf$kappa), collapse = " | ")))
}
