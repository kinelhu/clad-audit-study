# 02_corpus_flow.R
# -----------------------------------------------------------------------
# Corpus overview: (1) growth over time (Figure-1A idiom: annual bars + cumulative
# line + milestone markers), (2) Table 1 as a population, stratified by study design,
# (3) a PRISMA-style flow. No baked-in titles; text in the legends.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

# ---- (1) corpus over time: stacked annual volume by intervention/observation + cumulative total ----
# Axis = evaluates_intervention (the classifier's ROBUST, "stated-fact" field, reliable across ALL screened
# records — unlike study_design, which is abstract-only and unreconciled for the un-retrieved ~70%). STACKED bars =
# annual volume split into interventional (red, at the BOTTOM so its small persistent share is axis-anchored and
# legible) vs observational/other (blue); a thin dark line = CUMULATIVE total on a secondary axis (flow + stock in
# one panel). No rolling mean — bars carry the raw annual counts, the cumulative line is inherently smooth.
# Population = the ANALYZABLE cohort (`an`), the same n used by every other exhibit. This panel used the
# abstract-eligible universe while retrieval was incomplete, because the analyzable cohort was then a
# retrieval-biased sample of it. Retrieval closed at 95.1% of eligible studies on 2026-08-12, so that
# reason no longer applies. The claim the panel supports is correspondingly narrower: growth of the
# analyzable literature, not of every abstract-eligible record. Changed 2026-08-13.
corpus_all <- an |>
  mutate(year = suppressWarnings(as.numeric(year))) |>
  filter(!is.na(year), year >= 2005, year <= 2026) |>
  mutate(stype = factor(if_else(is_interventional %in% c(TRUE, "True"), "Interventional", "Observational / other"),
                        levels = c("Observational / other", "Interventional")))   # Interventional last -> bottom of stack
by_yr  <- corpus_all |> count(year, stype, name = "n")
cumtot <- corpus_all |> count(year, name = "n") |> arrange(year) |> mutate(cum = cumsum(n))
sf     <- max(cumtot$cum) / max(cumtot$n)                    # scale the cumulative onto the annual-count axis
cend   <- cumtot |> slice_max(year, n = 1)
pal_st <- c("Observational / other" = clad_blue, "Interventional" = clad_red)
milestones <- tribble(~year, ~label, 2011, "RAS phenotype\ndescribed", 2019, "ISHLT CLAD\nconsensus")
y_top <- max(cumtot$n) * 1.15

pt <- ggplot() +
  geom_col(data = by_yr, aes(year, n, fill = stype), width = 0.8) +
  geom_vline(data = milestones, aes(xintercept = year), linetype = "dashed", colour = "grey50", linewidth = 0.4) +
  geom_line(data = cumtot, aes(year, cum / sf), colour = "grey30", linewidth = 0.5) +
  geom_text(data = cend, aes(year, cum / sf, label = cum), colour = "grey30", size = 2.4, fontface = "bold", hjust = -0.15) +
  geom_text(data = milestones, aes(x = year + 0.25, y = y_top, label = label),
            hjust = 0, vjust = 1, size = 2.4, colour = "grey30", lineheight = 0.9) +
  scale_fill_manual(values = pal_st, name = NULL, breaks = c("Observational / other", "Interventional")) +
  scale_x_continuous(breaks = seq(2005, 2025, 5), expand = expansion(mult = c(0.01, 0.06))) +
  scale_y_continuous(name = "Publications / year",
                     sec.axis = sec_axis(~ . * sf, name = "Cumulative publications"),
                     limits = c(0, y_top), expand = expansion(mult = c(0, 0.02))) +
  labs(x = NULL)
save_fig("F_corpus_time", pt, width = fig_w2, height = 4.0)
write_legend("F_corpus_time", paste0(
  "**Figure. Growth of the clinical lung-transplant CLAD-outcome literature, 2005–2026.** Stacked bars, annual ",
  "publications split into studies that evaluate an intervention (red) versus observational or other designs (blue), ",
  "classified from the title/abstract; dark line, cumulative total (right axis); dashed lines, field milestones ",
  "(n = ", cm(sum(cumtot$n)), " analyzable studies with a resolvable year; reviews, methods papers, case ",
  "reports, and non-clinical studies excluded by the abstract gate). ",
    "*Abbreviations:* CLAD, chronic lung allograft dysfunction; ISHLT, International Society for Heart and Lung ",
  "Transplantation; RAS, restrictive allograft syndrome."))

# ---- (2) Table 1 as a population, by study design -----------------------------
# Journal collapsed to the most frequent titles + a pooled remainder, so the table
# shows which journals publish the CLAD-outcome literature within each study design.
n_journ <- dplyr::n_distinct(an$journal)
top_journ <- an |> count(journal, sort = TRUE) |> slice_head(n = 6) |> pull(journal)
short_journ <- function(j) dplyr::case_when(
  str_detect(j, "American journal of transplantation") ~ "Am J Transplant",
  str_detect(j, "Journal of heart and lung transplantation") ~ "J Heart Lung Transplant",
  str_detect(j, fixed("JHLT open"))            ~ "JHLT Open",
  str_detect(j, "Transplantation proceedings") ~ "Transplant Proc",
  str_detect(j, "Transplantation direct")      ~ "Transplant Direct",
  str_detect(j, "Transplant international")     ~ "Transpl Int",
  TRUE ~ NA_character_)
t1 <- an |>
  transmute(
    study_design = fct_recode(fct_drop(study_design),
        "RCT" = "rct", "Prospective cohort" = "prospective_cohort",
        "Retrospective cohort" = "retrospective_cohort", "Registry" = "registry",
        "Cross-sectional" = "cross_sectional", "Other" = "other"),
    `Outcome role` = fct_recode(fct_drop(outcome_role), Primary = "primary", Secondary = "secondary"),
    `Era` = era, `Interventional` = is_interventional,   # source format (XML vs PDF) dropped: an extraction-provenance detail, not a study characteristic
    `Funding source` = factor(dplyr::recode(funding,
        industry = "Industry / mixed", mixed = "Industry / mixed",
        public_nonprofit = "Public / non-profit", none_stated = "Not stated", unclear = "Unclear"),
        levels = c("Industry / mixed", "Public / non-profit", "Not stated", "Unclear")),
    `Journal` = fct_infreq(factor(coalesce(short_journ(journal),
                 sprintf("Other (%d journals)", n_journ - length(top_journ))))) |>
                 forcats::fct_relevel(sprintf("Other (%d journals)", n_journ - length(top_journ)), after = Inf),
    `Sample size` = sample_size, `Min-set items (0-5)` = n_minset
  ) |>
  tbl_summary(by = study_design,
    type = list(c(`Sample size`, `Min-set items (0-5)`) ~ "continuous"),
    statistic = list(all_continuous() ~ "{median} [{p25}-{p75}]", all_categorical() ~ "{n} ({p}%)"),
    missing = "no") |>
  add_overall() |> modify_header(label = "**Characteristic**") |> bold_labels()
# Two exhibits count "interventional" differently on purpose: this table reports the classifier flag, the
# trials landscape also admits metadata-RCTs that lack it. Both numbers are derived here so the footnote
# reconciling them cannot drift from either exhibit. (06_trials_landscape.R applies the wider filter.)
.n_flag <- sum(an$evaluates_intervention %in% TRUE)
.n_rct_unflagged <- sum(an$study_design %in% "rct" & !(an$evaluates_intervention %in% TRUE))
save_tbl(t1, "T1_corpus",
         footer = sprintf(paste0("n = %s patient-level studies with CLAD as a primary or secondary outcome. ",
           "Continuous variables are median [IQR]; categorical variables n (%%). Study design (the columns) is ",
           "reconciled from bibliographic metadata (authoritative for randomized trials and registries) and the ",
           "full-text extraction; the interventional flag is from the title/abstract classifier. The ",
           "interventional row counts that flag alone (%s studies); the supplementary interventional-landscape ",
           "exhibit uses a slightly wider definition that also admits %s randomized trials lacking the flag, ",
           "and so totals %s. ",
           "*Abbreviations:* CLAD, chronic lung allograft dysfunction; IQR, interquartile range; JHLT, The Journal ",
           "of Heart and Lung Transplantation; RCT, randomized controlled trial."),
           cm(nrow(an)), cm(.n_flag), cm(.n_rct_unflagged), cm(.n_flag + .n_rct_unflagged)),
         # 8 columns of design strata: portrait squeezes every cell to a two-line stack.
         landscape = TRUE)

# ---- (3) PRISMA-style flow: eligibility BEFORE retrieval (fixed-height boxes) --
# Counts come from _coverage.R (single source). The spine follows the eligible-universe
# logic: the abstract classifier defines eligibility across ALL screened records, so
# retrieval is a coverage fraction WITHIN a defined universe rather than an open-ended
# loss. Three side boxes carry the exclusions: abstract-ineligible (before retrieval),
# eligible-but-not-retrieved (the paywalled gap), and excluded-on-full-text (after reading).
source(file.path(dir_analysis, "_coverage.R"))
bh <- 0.40; bw <- 2.2; ex0 <- 2.7; ex1 <- 6.9    # box half-height/width; exclusion box x-range (widened so text fits)
fsz <- lab_size + 0.35                            # flow-box text, a touch larger than the on-plot default
esz <- lab_size - 0.05                            # exclusion-box text: denser, so slightly smaller than the flow boxes

# PRISMA 2020 item 16a wants the flow to START AT IDENTIFICATION. It began at "records screened", with
# the 1,953 identified and the 30 non-original records removed at parsing appearing only in the running
# text — an incomplete flow diagram in a paper auditing reporting completeness. Both stages are boxes now.
flow <- tibble(
  label = c("Records identified\n(PubMed, searched 5 August 2026)",
            "Records screened\n(title/abstract, 2005–2026)",
            "Eligible studies\n(abstract-defined)",
            "Full text retrieved\nand screened",
            "Analyzable cohort:\nCLAD an analysed outcome"),
  n = c(n_identified, n_screened, n_eligible, n_retr_elig, n_analyzable_cov)) |>
  mutate(y = rev(seq_len(n())), txt = sprintf("%s\n(n = %s)", label, cm(n)))
arrows <- tibble(y0 = flow$y[-nrow(flow)] - bh, y1 = flow$y[-1] + bh)   # box bottom -> next box top
excl <- tribble(~y, ~txt,
  # PRISMA "records removed before screening". The gap y-values track the flow boxes above: with five
  # boxes at y = 5..1, the inter-box gaps are 4.5, 3.5, 2.5, 1.5.
  4.5, sprintf(paste0("Removed before screening (n = %s):\nnon-original publication types\n",
                      "(preprints, protocols, errata,\nproceedings, retractions)"), cm(n_identified - n_screened)),
  3.5, sprintf("Abstract-ineligible (n = %s):\nnon-clinical / animal / in-vitro,\nreviews, methods, case reports", cm(n_ineligible)),
  # Wording finalised 2026-08-12, after institutional access was exhausted: these are not "not yet
  # fetched" but genuinely unobtainable — paywalled titles that neither the automated routes nor the
  # institution's own subscriptions could reach. The retrieval MECHANISM (automated vs library) is
  # deliberately not broken out here: it is pipeline plumbing, not information a clinical reader needs.
  2.5, sprintf("Full text unobtainable (n = %s):\npaywalled, with no institutional\naccess available", cm(n_notretr_elig)),
  1.5, sprintf(paste0("Excluded on full text (n = %s):\nCLAD not an analysed outcome /\ndescriptor; mechanistic w/o ",
                      "exposure;\nrecipients not lung transplant (n = %s);\ntrial protocol, no results (n = %s)"),
               cm(n_excl_ft), cm(n_notlung), cm(n_protocol)))
pf <- ggplot() +
  geom_segment(data = arrows, aes(x = 0, xend = 0, y = y0, yend = y1),
               arrow = arrow(length = unit(7, "pt"), type = "closed"), colour = "grey40", linewidth = 0.5) +
  geom_segment(data = excl, aes(x = 0, xend = ex0, y = y, yend = y), colour = "grey55", linewidth = 0.4) +
  geom_rect(data = excl, aes(xmin = ex0, xmax = ex1, ymin = y - bh, ymax = y + bh),
            fill = "grey97", colour = "grey55", linewidth = 0.4) +
  geom_text(data = excl, aes((ex0 + ex1) / 2, y, label = txt), size = esz, lineheight = 0.95) +
  geom_rect(data = flow, aes(xmin = -bw, xmax = bw, ymin = y - bh, ymax = y + bh),
            fill = "grey95", colour = "black", linewidth = 0.45) +
  geom_text(data = flow, aes(0, y, label = txt), size = fsz, lineheight = 0.95) +
  scale_x_continuous(limits = c(-bw - 0.1, ex1 + 0.1)) +
  # Derived from the boxes rather than hardcoded: this was c(0.5, 4.5), sized for four flow boxes, and
  # adding the identification stage silently clipped the top box and half its exclusion note off-canvas.
  scale_y_continuous(limits = c(min(flow$y) - bh - 0.2, max(c(flow$y, excl$y)) + bh + 0.2)) +
  theme_void() + theme(plot.margin = margin(6, 6, 6, 6))
save_fig("F_flow", pf, width = fig_w2, height = 0.95 * nrow(flow))

# ---- combined MAIN panel: study flow (A) + cumulative studies by type (B) ----
# Give the flow (A) more of the height than the cumulative plot (B) — its boxed text needs the room.
F_corpus_flow <- (pf / pt) + patchwork::plot_layout(heights = c(1.35, 1)) +
  patchwork::plot_annotation(tag_levels = "A") &
  ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold", size = 12))
save_fig("F_corpus_flow", F_corpus_flow, width = fig_w2, height = 8.6)   # +1 flow box (identification)
# Legend rewritten 2026-08-12: describe the panels, nothing else. The previous version ran to ~150 words,
# explained WHY the non-retrieved skew recent, and cross-referenced a supplementary table — all of which is
# Results/Limitations material, not a figure legend.
write_legend("F_corpus_flow", paste0(
  "**Corpus and study flow.** (A) PubMed records through title/abstract screening to the analyzable cohort. ",
  "Eligibility was defined from the title/abstract for every screened record; full text was then read to confirm ",
  "CLAD as an analysed outcome and lung transplant recipients as the analysed population. (B) Annual ",
  "publications among the analyzable studies, split into those ",
  "evaluating an intervention (red) and observational or other designs (blue); the dark line is the cumulative ",
  "total (right axis). *Abbreviation:* CLAD, chronic lung allograft dysfunction."))

message("02 complete: F_corpus_time, T1_corpus (by study design), F_flow, F_corpus_flow (panel).")
