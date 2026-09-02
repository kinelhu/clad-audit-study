# 06_trials_landscape.R
# -----------------------------------------------------------------------
# The interventional landscape of the CLAD-outcome literature — companion to Cravedi et al.,
# Transplantation 2025;109:411-417 ("Where are the trials?"). Among analyzable clinical studies
# (the `an` frame), those that EVALUATE an intervention (abstract-classifier `evaluates_intervention`,
# the authoritative flag; the full-text pass is a comparator only), stratified by DESIGN RIGOR:
# randomized trial / prospective (non-randomized) / retrospective-or-other. This shows both the
# activity (what is tested) and the scarcity of actual trials — Cravedi's point, quantified.
#
# Reliability: RCT is triangulated across the bibliographic metadata (route.py) AND both LLM passes
# (a strong, stated fact — high confidence). The prospective-vs-retrospective boundary is softer
# (harder to classify from text than randomized status) and is reported with that caveat.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

# COHORT = studies evaluating an intervention (abstract classifier) PLUS any metadata-confirmed RCT.
# The RCT admission is deliberate and was re-instated 2026-08-13. PubMed's "Randomized Controlled Trial"
# pubtype also tags SECONDARY ANALYSES of trial cohorts (PMID 29087035, neurocognition in participants from
# a prior RCT; PMID 26168736, BAL neutrophilia in azithromycin-treated recipients). Those are trial results
# as the field counts them, and excluding them would make this figure's randomized count disagree with the
# RCT stratum of Table 1 — an N discrepancy between exhibits is worse than a broad definition.
# They are classified by the residual rules in build_frame (title fallback), not left in a "Not specified" bar.
int <- an |>
  filter(is_interventional %in% c(TRUE, "True") | study_design %in% "rct") |>
  mutate(
    iclass = if_else(is.na(class_intervention) | class_intervention == "", "Not specified", class_intervention),
    # RCT status comes from the RECONCILED `study_design`, not "any signal", so this figure cannot disagree
    # with Table 1. The example this comment used to cite was itself a casualty of the substring bug fixed
    # 2026-08-31: PMID 31687370 is the 21-patient inhaled-liposomal-ciclosporin BOS trial, called a registry
    # only because its abstract reads "standard-of-care (SOC) oral immUNOSuppression". PubMed tags it
    # "Journal Article" alone, so metadata never saw the trial; the model read the full text, said rct, and
    # was overruled. It is now correctly a randomized trial. Kept as a warning: a comment that explains why
    # the pipeline's odd answer is right is the shape a rationalised bug takes.
    is_rct = study_design %in% "rct",
    rigor = factor(case_when(
        is_rct                                  ~ "Randomized trial",
        study_design_ab == "prospective_cohort" ~ "Prospective (non-randomized)",
        TRUE                                    ~ "Retrospective / other"),
      levels = c("Randomized trial", "Prospective (non-randomized)", "Retrospective / other")),
    intent = factor(case_when(   # REPORTED intent = full-text intervention_intent (3-value, risk-factor folded into prevention)
        intervention_intent == "prevent_clad" ~ "Prevention",
        intervention_intent == "treat_clad"   ~ "Treatment of established CLAD",
        TRUE                                  ~ NA_character_),
      levels = c("Prevention", "Treatment of established CLAD")))
n_int <- nrow(int)
# Studies carrying the classifier's interventional flag — the quantity the corpus table's "Interventional"
# row reports. n_int is larger by the metadata-RCTs that lack the flag; the footer states the difference
# so the two exhibits cannot be read as disagreeing.
n_flagged <- sum(an$evaluates_intervention %in% TRUE)
n_rct <- sum(int$rigor == "Randomized trial")
n_pro <- sum(int$rigor == "Prospective (non-randomized)")
n_ret <- sum(int$rigor == "Retrospective / other")
med_n <- suppressWarnings(median(int$sample_n_ab, na.rm = TRUE))
pal_rig <- c("Randomized trial" = "#2166AC", "Prospective (non-randomized)" = clad_blue,
             "Retrospective / other" = "#C6DBEF")

# ---- Panel A: therapeutic class, stacked by design rigor --------------------
# reverse = TRUE stacks the RIGOR segments from the axis outward, so every bar starts with its
# randomized studies at x = 0. Stacked the default way, the RCT segment floats at the tip of a long
# retrospective trunk at a different offset in every row, and the counts cannot be compared by eye.
pA <- int |> count(iclass, rigor) |>
  mutate(iclass = fct_reorder(iclass, n, sum)) |>
  ggplot(aes(n, iclass, fill = rigor)) +
  geom_col(width = 0.75, position = position_stack(reverse = TRUE)) +
  scale_fill_manual(values = pal_rig, name = NULL, drop = FALSE) +
  scale_x_continuous(expand = expansion(mult = c(0, 0.06))) +
  labs(x = "Studies evaluating the intervention", y = NULL)

# ---- Panel B: intent, stacked by design rigor ------------------------------
pB <- int |> filter(!is.na(intent)) |> count(intent, rigor) |>
  ggplot(aes(n, intent, fill = rigor)) +
  geom_col(width = 0.55, position = position_stack(reverse = TRUE)) +
  scale_fill_manual(values = pal_rig, name = NULL, drop = FALSE, guide = "none") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.06))) +
  labs(x = "Studies evaluating the intervention", y = NULL)

pp <- pA / pB + patchwork::plot_layout(heights = c(3, 1)) + patchwork::plot_annotation(tag_levels = "A")
save_fig("F_trials_landscape", pp, width = fig_w2, height = 6.5)

# Enumerate the RESIDUAL classes in the legend, generated from the data rather than hand-written.
# A catch-all bucket nobody can see into is how "Other pharmacological" grew into the second-largest
# bar while maintenance immunosuppression had no category at all. Listing its members keeps it honest
# and self-limiting: if the list stops fitting in a legend, the taxonomy needs another class.
resid_txt <- function(cls) {
  v <- int |> filter(iclass == cls) |>
    transmute(t = stringr::str_squish(dplyr::coalesce(intervention, ""))) |>
    filter(t != "") |> pull(t)
  if (!length(v)) return(NULL)
  # keep the source capitalisation: tolower() here mangled proper nouns (Perfadex, SARS-CoV-2, Celsior).
  sprintf("*%s* comprises %s.", cls, paste(sort(unique(v)), collapse = "; "))
}
resid_note <- paste(stats::na.omit(c(resid_txt("Surgical (other)"), resid_txt("Other"))), collapse = " ")
write_legend("F_trials_landscape", paste0(
  "**Figure. Interventional landscape of the CLAD-outcome literature, by therapeutic class and design.** ",
  n_int, " analyzable studies evaluate a therapy, procedure, or protocol against CLAD, grouped by therapeutic ",
  "class (A) and intent (B) and shaded by design: randomized trial (darkest; n = ", n_rct, "), prospective ",
  "non-randomized (n = ", n_pro, "), or retrospective/other (lightest; n = ", n_ret, "); median study size ",
  ifelse(is.na(med_n), "NA", as.character(round(med_n))), " recipients. Intent (B) is prevention versus ",
  "treatment of established CLAD; studies with no therapeutic intent (transplant-type, donor, or policy ",
  "comparisons) are omitted. Preclinical and descriptor-only studies are excluded. ", resid_note, " ",
  "*Abbreviations:* CLAD, chronic lung allograft dysfunction; IS, immunosuppression; RCT, randomized controlled trial."))

save_df_tbl(int |> count(iclass, rigor) |> pivot_wider(names_from = rigor, values_from = n, values_fill = 0) |>
              rename(`Intervention class` = iclass),
            "T_trials_landscape",
            caption = "Studies evaluating an intervention against CLAD, by therapeutic class and design rigor",
            # The old footer explained the count in the WRONG DIRECTION: it said the randomized count here is
            # lower than the corpus table's RCT column because two trial-cohort secondary analyses "do not
            # evaluate an intervention". The filter above deliberately keeps those two, so the randomized
            # count MATCHES the corpus table at n_rct, and it is the interventional TOTAL that is two higher
            # than the corpus table's interventional row. Stated correctly now. (Peer review 2026-08-15.)
            footer = sprintf(paste0("n = %s analyzable studies evaluating an intervention against CLAD; %d ",
              "randomized, %d prospective non-randomized, %d retrospective/other. This total is %d higher than ",
              "the interventional row of the corpus table, which counts only the title/abstract classifier's ",
              "interventional flag: %d studies carry the randomized-trial publication type without that flag ",
              "(secondary analyses of trial cohorts) and are included here, so the randomized count agrees with ",
              "the corpus table's randomized-trial column. *Abbreviations:* CLAD, chronic lung allograft ",
              "dysfunction; CMV, cytomegalovirus; IS, immunosuppression; mTOR, mechanistic target of rapamycin; ",
              "RCT, randomized controlled trial."),
                             cm(n_int), n_rct, n_pro, n_ret, n_int - n_flagged, n_int - n_flagged))

message(sprintf("06 complete: %d evaluate-intervention | %d RCT, %d prospective, %d retrospective | median N=%s.",
                n_int, n_rct, n_pro, n_ret, ifelse(is.na(med_n), "NA", as.character(round(med_n)))))
