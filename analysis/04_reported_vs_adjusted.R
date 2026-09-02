# 04_reported_vs_adjusted.R
# -----------------------------------------------------------------------
# Among studies WITH a multivariable CLAD model, for each immunological / second-hit
# covariate: adjusted for, reported but not adjusted, or not reported. Ordered by the
# adjusted share (covariates the field actually models -> covariates it never does).
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

# Analytic approach to CLAD (from the decoupled clad_model pass): multivariable model / univariable-or-KM only /
# no exposure->CLAD regression. Reported-vs-adjusted is conditioned on the MULTIVARIABLE studies (the only ones
# that could have adjusted), with the other two reported as their own, milder category. See docs/decision-log.md.
an <- an |> mutate(model_type = factor(model_type, levels = c("multivariable", "univariable_only", "none")))
mt_tab <- an |> count(model_type, .drop = FALSE) |> mutate(pct = n / sum(n)) |>
  transmute(`Analytic approach to CLAD` = dplyr::recode(model_type,
              multivariable = "Multivariable CLAD model", univariable_only = "Univariable / log-rank only",
              none = "No exposure-CLAD regression"), n, `%` = pct(pct))
save_df_tbl(mt_tab, "T_model_type", caption = "Analytic approach to CLAD in the analyzable cohort",
            footer = sprintf(paste0("n = %s analyzable studies, from the study-level CLAD-model extraction pass. ",
              "*Multivariable* = a regression for CLAD with two or more covariates fitted together; *univariable / ",
              "log-rank only* = single-covariate associations or Kaplan-Meier with log-rank, no joint model; *none* = ",
              "no exposure-to-CLAD regression. *Abbreviations:* CLAD, chronic lung allograft dysfunction."), nrow(an)))

# Model-fitting over calendar time (publication year) — a secondary outcome: has multivariable modelling improved?
td <- an |> mutate(yr = suppressWarnings(as.numeric(year)), mv = as.integer(model_type == "multivariable")) |> filter(!is.na(yr))
mfit <- glm(mv ~ yr, family = binomial, data = td)
or_dec <- exp(coef(mfit)[["yr"]] * 10); ci_dec <- exp(confint.default(mfit)["yr", ] * 10)
pv_dec <- summary(mfit)$coefficients["yr", "Pr(>|z|)"]
yr_prop <- td |> group_by(yr) |> summarise(n = n(), p = mean(mv), .groups = "drop")
p_tr <- ggplot(td, aes(yr, mv)) +
  geom_smooth(method = "glm", method.args = list(family = binomial), se = TRUE,
              color = "#2166AC", fill = "#4393C3", alpha = 0.15, linewidth = 0.9) +
  geom_point(data = yr_prop, aes(yr, p, size = n), alpha = 0.45, color = "#2166AC") +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1), limits = c(0, 1), expand = expansion(mult = c(0, .02))) +
  scale_size_area(max_size = 6, name = "studies / yr") +
  labs(x = "Publication year", y = "Fit a multivariable CLAD model")
save_fig("F_model_trend", p_tr, width = fig_w2, height = 4.1)
write_legend("F_model_trend", paste0(
  "**Figure. Multivariable modelling of CLAD over time.** Proportion of analyzable studies fitting a multivariable ",
  "model for CLAD by publication year (points sized by the number of studies that year); the line is a logistic fit ",
  "with a 95% confidence-interval band. *Abbreviation:* CLAD, chronic lung allograft dysfunction."))

model_studies <- an |> filter(model_type == "multivariable")
items_bc <- panel |> filter(tier %in% c("B", "C")) |> pull(key)

long <- model_studies |>
  select(pmid, all_of(paste0("score_", items_bc)), all_of(paste0("adj_", items_bc))) |>
  pivot_longer(-pmid, names_to = c(".value", "key"), names_pattern = "(score|adj)_(.*)") |>
  mutate(cat = factor(case_when(
      adj                              ~ "Adjusted for",
      score %in% c("full", "partial")  ~ "Reported, not adjusted",
      TRUE                             ~ "Not reported"),
      levels = c("Not reported", "Reported, not adjusted", "Adjusted for"))) |>
  left_join(panel, by = "key")

comp <- long |> count(tier_label, key, label, min_set, cat) |>
  group_by(key) |> mutate(pct = n / sum(n)) |> ungroup()

ord <- comp |> filter(cat == "Adjusted for") |> arrange(pct) |> mutate(item = ms_md(label, min_set))

# Segment-value labels (black): the adjusted (blue) and reported-not-adjusted (red) share of each covariate, placed
# just past the RIGHT EDGE of its own segment — short blue segments can't hold a label inside, so all sit outside.
# Not-reported (grey) is left unlabelled. x_rep is the cumulative blue+red edge, so the red value sits at the red
# segment's right end.
seg_lab <- comp |>
  select(key, label, min_set, cat, pct) |>
  tidyr::pivot_wider(names_from = cat, values_from = pct, values_fill = 0) |>
  transmute(item = factor(ms_md(label, min_set), levels = ord$item),
            adj = `Adjusted for`, rep = `Reported, not adjusted`,
            x_adj = `Adjusted for`, x_rep = `Adjusted for` + `Reported, not adjusted`)

p <- comp |>
  mutate(item = factor(ms_md(label, min_set), levels = ord$item)) |>
  ggplot(aes(pct, item, fill = cat)) +
  geom_col(width = 0.75) +
  geom_text(data = seg_lab, aes(x = x_adj, y = item, label = scales::percent(adj, accuracy = 1)),
            inherit.aes = FALSE, hjust = -0.18, size = lab_size, colour = "black") +
  geom_text(data = seg_lab, aes(x = x_rep, y = item, label = scales::percent(rep, accuracy = 1)),
            inherit.aes = FALSE, hjust = -0.18, size = lab_size, colour = "black") +
  scale_fill_manual(values = pal_radj, name = NULL) +
  scale_x_continuous(labels = scales::percent_format(accuracy = 1),
                     breaks = c(0, .25, .5, .75, 1), expand = expansion(mult = c(0, 0.06))) +
  labs(x = sprintf("Share of the %d multivariable-model studies", nrow(model_studies)), y = NULL) +
  theme(axis.text.y = ggtext::element_markdown())
# NB: `p` is NOT saved as a standalone figure — it is panel A of F_confounding (built below). The former
# standalone F_reported_vs_adjusted was a redundant twin of that panel and was dropped 2026-08-09 (it was
# generated but never cited; the manuscript uses F_confounding). Its numeric companion T_reported_vs_adjusted stays.

tab <- comp |> select(tier_label, label, min_set, cat, pct) |>
  pivot_wider(names_from = cat, values_from = pct, values_fill = 0) |>
  transmute(Tier = tier_label, Covariate = ms_mark(label, min_set),
            `Adjusted` = pct(`Adjusted for`), `Reported, not adjusted` = pct(`Reported, not adjusted`),
            `Not reported` = pct(`Not reported`), .a = `Adjusted for`) |>
  arrange(Tier, desc(.a)) |>                            # tier sections (show_table group_col="Tier"), by adjusted share within
  mutate(Tier = as.character(Tier)) |> select(-.a)
save_df_tbl(tab, "T_reported_vs_adjusted",
            caption = "Reported versus adjusted-for covariates among studies with a multivariable CLAD model",
            footer = sprintf(paste0("Numeric companion to the confounding figure. Among the %d studies that fit a ",
              "multivariable model for CLAD, the percentage of each immunological or second-hit covariate that was ",
              "adjusted for (entered in the model), reported but not entered, or not reported. Each share is rounded ",
              "independently, so segments may not sum exactly to 100%% or to a total quoted in the text. ",
              "Covariates are grouped by panel tier and ordered within tier by the adjusted share. * minimum ",
              "immunological set. *Abbreviations:* ACR, acute ",
              "cellular rejection; AMR, antibody-mediated rejection; CLAD, chronic lung allograft dysfunction; CMV, ",
              "cytomegalovirus; cPRA, calculated panel-reactive antibody; D/R, donor/recipient; DSA, ",
              "donor-specific antibody; GERD, gastro-oesophageal ",
              "reflux disease; HLA, human leucocyte antigen; IS, immunosuppression; PGD, primary graft ",
              "dysfunction."), nrow(model_studies)),
            group_col = "Tier")

# ---- immunological-set comprehensiveness (Panel B): how many of the immunological determinants per model ----
# The min-set determinants excluding the CLAD-definition outcome anchor, derived from the panel flag so it
# tracks membership changes automatically (induction dropped from the min-set 2026-08-08).
imm_det <- setdiff(panel$key[panel$min_set], "clad_definition")
nimm <- rowSums(model_studies[paste0("adj_", imm_det)])
comp_df <- tibble(k = factor(pmin(nimm, 3), levels = 0:3, labels = c("0", "1", "2", "3+"))) |>
  count(k, .drop = FALSE) |> mutate(pct = n / sum(n))
p_comp <- ggplot(comp_df, aes(k, pct)) +
  geom_col(fill = "#4393C3", width = 0.68) +
  geom_text(aes(label = pct(pct)), vjust = -0.4, size = lab_size) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1), expand = expansion(mult = c(0, 0.12))) +
  labs(x = sprintf("Determinants\nadjusted for\n(of %d)", length(imm_det)), y = "Multivariable studies")

# ---- combined MAIN panel: reported-vs-adjusted (A, wide) + immunological comprehensiveness (B, thin) ----
F_confounding <- (p | p_comp) + patchwork::plot_layout(widths = c(2.9, 1)) +
  patchwork::plot_annotation(tag_levels = "A") &
  ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold", size = 12))
save_fig("F_confounding", F_confounding, width = fig_w2, height = 4.5)
write_legend("F_confounding", paste0(
  "**Confounding control in CLAD studies.** (A) Among the ", nrow(model_studies), " studies that fit a multivariable ",
  "model for CLAD, the share of each immunological or second-hit covariate adjusted for (blue), reported but not ",
  "entered in the model (red), or not reported (grey); covariates are ordered by the adjusted share; the adjusted ",
  "and reported-but-not-adjusted percentages are printed in black beside their segments (not reported is unlabelled) ",
  "and minimum-set covariates are shown in bold blue. (B) Number of the five ",
  "immunological minimum-set determinants (CMV D/R, HLA ",
  "mismatch, maintenance IS, ACR, AMR) that each of these models adjusts for. *Abbreviations:* ACR, acute cellular rejection; AMR, ",
  "antibody-mediated rejection; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; D/R, ",
  "donor/recipient; DSA, donor-specific antibody; HLA, human leucocyte antigen; IS, immunosuppression; ",
  "PGD, primary graft dysfunction."))

message(sprintf("04 complete: %d studies with a multivariable CLAD model.", nrow(model_studies)))
