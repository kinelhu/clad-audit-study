# 01_completeness_landscape.R
# -----------------------------------------------------------------------
# Per-covariate reporting completeness among analyzable studies: not / partial /
# full, over the applicable denominator (conditional-inapplicable and non-returned
# items excluded). Output: table (docx/csv) + tier-faceted figure (pdf/png) + legend.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))
suppressPackageStartupMessages(library(ggtext))

comp <- scores_long(an) |>
  filter(applicable) |>
  count(tier, tier_label, key, label, min_set, score, name = "n") |>
  group_by(key) |> mutate(n_appl = sum(n), pct = n / n_appl) |> ungroup()

# ---- table: item x {full, partial, not}, worst-reported first ----------------
tab <- comp |>
  select(tier_label, label, min_set, score, pct, n_appl) |>
  pivot_wider(names_from = score, values_from = pct, values_fill = 0) |>
  transmute(Tier = tier_label, Covariate = ms_mark(label, min_set), `N` = n_appl,
            `Full` = pct(full), `Partial` = pct(partial), `Not reported` = pct(not),
            .not = not) |>
  arrange(Tier, desc(.not)) |>                          # match F_completeness_landscape: tier sections, worst-first within tier
  mutate(Tier = as.character(Tier)) |>                  # Tier is the group column (show_table(group_col="Tier") → section header rows)
  select(-.not)
save_df_tbl(tab, "T_completeness_landscape",
            caption = "Reporting completeness of CLAD covariates",
            footer = sprintf(paste0("Percentage of applicable analyzable studies (n = %s) reporting each covariate ",
              "fully, partially, or not at all, grouped by panel tier and ordered within tier by the not-reported ",
              "share. The denominator therefore varies by covariate and is given per row: conditional items are ",
              "scored only in the population that makes them applicable. Two conditional triggers (competing risk, ",
              "follow-up and censoring) are applied deterministically from the study's analysis type; the rest are ",
              "the extraction's own judgement and were not validated; the applicable N is given for every row. ",
              "No study selected by the CYP3A5 trigger reports expressor status. * minimum ",
              "immunological set. *Abbreviations:* ACR, acute cellular rejection; AMR, antibody-mediated rejection; ",
              "BOS, bronchiolitis obliterans syndrome; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; ",
              "CNI, calcineurin inhibitor; cPRA, calculated panel-reactive antibody; CYP3A5, cytochrome P450 3A5; D/R, donor/recipient; ",
              "DBD, donation after ",
              "brain death; DCD, donation after circulatory death; DSA, donor-specific antibody; EVLP, ex-vivo lung ",
              "perfusion; FEV1, forced expiratory volume in one second; GERD, gastro-oesophageal reflux disease; HLA, ",
              "human leucocyte antigen; IS, immunosuppression; PGD, primary graft dysfunction; RAS, restrictive ",
              "allograft syndrome."), nrow(an)),
            group_col = "Tier")

# Shorten a few unwieldy labels FOR THE FIGURE ONLY (the table keeps the full names) so long y-labels don't
# squeeze the plotting panel at double-column width.
fig_short <- c(
  "Reversible/azithromycin-responsive dysfunction excluded" = "Reversible dysfunction excluded",
  "Pseudomonas/Aspergillus colonization" = "Pseudomonas / Aspergillus",
  "Pre-tx immunosuppression exposure"    = "Pre-tx IS exposure",
  "CMV infection/disease events"         = "CMV infection / disease",
  "Eplet / molecular HLA mismatch"       = "Eplet / molecular HLA",
  "CNI intra-patient variability"        = "CNI variability")
comp <- comp |> mutate(label = dplyr::recode(as.character(label), !!!fig_short))

# ---- figure: tier-faceted stacked bars, ordered within tier by % not ---------
ord <- comp |> filter(score == "not") |>
  group_by(tier_label, key, label, min_set) |> summarise(not = sum(pct), .groups = "drop") |>
  arrange(tier_label, not) |> mutate(item = ms_md(label, min_set))

p <- comp |>
  filter(score %in% c("not", "partial", "full")) |>
  mutate(score = factor(score, levels = c("not", "partial", "full")),
         item = factor(ms_md(label, min_set), levels = ord$item)) |>
  ggplot(aes(pct, item, fill = score)) +
  geom_col(width = 0.78) +
  facet_grid(tier_label ~ ., scales = "free_y", space = "free_y", switch = "y",
             labeller = as_labeller(c("Case-mix / context" = "Case-mix", "Core immunological" = "Immunological",
               "Non-alloimmune second hits" = "Second hits", "Novel / emerging" = "Emerging",
               "Outcome ascertainment" = "Outcome"))) +
  scale_fill_manual(values = pal_completeness, labels = completeness_labels, name = NULL) +
  scale_x_continuous(labels = scales::percent_format(accuracy = 1), expand = expansion(mult = c(0, 0.02))) +
  labs(x = "Share of applicable analyzable studies", y = NULL) +
  theme(strip.placement = "outside",
        strip.background = element_blank(),                      # drop the grey tier boxes
        strip.text.y.left = element_text(angle = 0, hjust = 1, face = "bold"),
        axis.text.y = ggtext::element_markdown(),                # bold-blue minimum-set labels
        panel.spacing = unit(3, "pt"))
save_fig("F_completeness_landscape", p, width = fig_w2, height = 7.4)

write_legend("F_completeness_landscape", paste0(
  "**Figure. Reporting completeness of CLAD covariates across the analyzable literature.** ",
  "Each bar is one covariate; segments give the percentage of applicable analyzable studies (n = ", cm(nrow(an)),
  " with CLAD as a primary or secondary outcome) reporting it fully, partially, or not at all. Covariates are ",
  "grouped by panel tier and ordered within tier by the not-reported share. Conditional covariates are scored ",
  "only in the population that makes them applicable and are excluded from other studies' denominators. ",
  "Covariates of the five-item minimum immunological set are shown in bold blue. ",
  "*Abbreviations:* ACR, acute cellular rejection; AMR, antibody-mediated rejection; CLAD, chronic lung allograft ",
  "dysfunction; CMV, cytomegalovirus; CNI, calcineurin inhibitor; DSA, donor-specific antibody; EVLP, ex-vivo lung ",
  "perfusion; FEV1, forced expiratory volume in one second; HLA, human leucocyte antigen; PGD, primary graft ",
  "dysfunction."))

message("01 complete: T_completeness_landscape + F_completeness_landscape.")

# ---- min-set x study design cross-table ---------------------------------------------------
# Per-item reporting (partial or full) over the applicable denominator, split by reconciled
# study_design. Cross-sectional is folded into "Other" (22 studies) to keep column n usable.
# No overall column: the all-studies rate is 100 - "Not reported" in T_completeness_landscape.
# No median row: the min-set count by design is already in Table 1.
des_lab <- c(rct = "RCT", prospective_cohort = "Prospective cohort",
             retrospective_cohort = "Retrospective cohort", registry = "Registry")
an_x <- an |> mutate(.des = factor(unname(ifelse(is.na(des_lab[as.character(study_design)]),
                                                 "Other", des_lab[as.character(study_design)])),
                                   levels = c(unname(des_lab), "Other")))
des_n <- an_x |> count(.des, name = "n_studies")

x_item <- scores_long(an_x |> select(pmid, .des, everything())) |>
  filter(applicable, min_set) |>
  left_join(an_x |> select(pmid, .des), by = "pmid") |>
  group_by(label, .des) |>
  summarise(rep = mean(score %in% c("partial", "full")), .groups = "drop")

xtab <- x_item |>
  mutate(v = pct(rep)) |>
  select(label, .des, v) |>
  pivot_wider(names_from = .des, values_from = v) |>
  # min-set items in the panel's own order. as.character() is required: panel$label is a FACTOR, and
  # c(factor, ...) coerces it to integer codes, so every item would match NA.
  mutate(.ord = match(label, as.character(panel$label[panel$min_set]))) |>
  arrange(.ord) |> select(-.ord) |> rename(Covariate = label)

col_n <- setNames(des_n$n_studies, as.character(des_n$.des))
names(xtab)[-1] <- sprintf("%s\n(n = %s)", names(xtab)[-1], col_n[names(xtab)[-1]])

save_df_tbl(xtab, "T_minset_by_design",
            caption = "Reporting of each minimum-set covariate, by study design",
            footer = paste0("Percentage of applicable studies reporting each minimum-set covariate at all ",
              "(partially or fully), by reconciled study design; cross-sectional studies are folded into Other. ",
              "Denominators vary ",
              "by covariate because conditional items are scored only where applicable. *Abbreviations:* ACR, ",
              "acute cellular rejection; AMR, antibody-mediated rejection; CMV, cytomegalovirus; D/R, ",
              "donor/recipient; HLA, human leucocyte antigen; IS, immunosuppression; RCT, randomized ",
              "controlled trial."))

# ---- supplementary methods: the scoring anchors -------------------------------------------------
# What "partial" and "full" mean for every covariate. Read from data/panel_anchors.csv, which
# build_frame generates from panel.py — the instrument documents itself rather than being retyped.
anch <- readr::read_csv(file.path(project_root, "data/panel_anchors.csv"), show_col_types = FALSE) |>
  mutate(across(everything(), ~ tidyr::replace_na(as.character(.x), "")),   # blank, not "NA", for unconditional items
         Tier = dplyr::recode(Tier, A = "Case-mix / context", B = "Core immunological",
                              C = "Non-alloimmune second hits", D = "Novel / emerging",
                              E = "Outcome ascertainment"))
save_df_tbl(anch, "T_panel_anchors",
            caption = "Scoring anchors for every covariate in the panel",
            footer = paste0("Each covariate is scored 0 (not reported), 1 (partial) or 2 (full) against these ",
              "anchors; every non-zero score required a verbatim supporting quote from the full text. ",
              "Conditional covariates are scored only in the population named in the final column, and are ",
              "otherwise not applicable and excluded from that covariate's denominator. * minimum ",
              "immunological set. *Abbreviations:* A1, A2, ISHLT histological grades of acute cellular ",
              "rejection; ACR, acute cellular rejection; AMR, antibody-mediated ",
              "rejection; AT1R, angiotensin II type 1 receptor; BOS, bronchiolitis obliterans syndrome; CLAD, ",
              "chronic lung allograft dysfunction; CMV, cytomegalovirus; CNI, calcineurin inhibitor; cPRA, ",
              "calculated panel-reactive antibody; CTD, ",
              "connective tissue disease; CV, coefficient of variation; CYP3A5, cytochrome P450 3A5; D/R, ",
              "donor/recipient; DBD, donation after brain death; DCD, donation after circulatory death; DMARD, ",
              "disease-modifying antirheumatic drug; DSA, donor-specific antibody; EVLP, ex-vivo lung perfusion; ",
              "FEV1, forced expiratory volume in one second; FISH, fluorescence in situ hybridization; FU, ",
              "follow-up; GERD, ",
              "gastro-oesophageal reflux disease; HLA, human leucocyte antigen; ILD, interstitial lung disease; ",
              "IPF, idiopathic pulmonary fibrosis; IPV, intra-patient variability; IQR, interquartile range; IS, ",
              "immunosuppression; ISHLT, International Society for Heart and Lung Transplantation; MFI, mean ",
              "fluorescence intensity; MICA, MHC class I chain-related gene A; mTOR, mechanistic target of ",
              "rapamycin; PF, pulmonary fibrosis; PGD, ",
              "primary graft dysfunction; PGx, pharmacogenomics; PIRCHE, predicted indirectly recognizable HLA ",
              "epitopes; PRA, ",
              "panel-reactive antibody; RAS, restrictive allograft syndrome; RTEL1, regulator of telomere ",
              "elongation helicase 1; SD, standard deviation; TERC, telomerase RNA component; TERT, ",
              "telomerase reverse transcriptase."),
            group_col = "Tier", landscape = TRUE)
