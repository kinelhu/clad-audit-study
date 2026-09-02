# 11_item_trends.R
# -----------------------------------------------------------------------
# Per-item reporting over calendar time. The minimum-set COUNT is flat across the study period
# (03_interpretability.R), but that composite averages over items moving in opposite directions:
# the alloantibody items (AMR, de novo DSA) rise steeply while the long-established ones (ACR,
# maintenance IS) erode. Reporting only the composite invites the obvious reviewer question
# ("surely AMR improved?"), so quantify the divergence directly.
#
# Outcome per item = reported at all (partial or full) over the APPLICABLE denominator; trend =
# logistic regression on calendar year, expressed per decade.
# Output: trajectories of the minimum-set items + a per-covariate period/trend table.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

# scores_long() does not carry `year` — joined explicitly, or `year` resolves to base::year().
sl <- scores_long(an) |>
  left_join(an |> select(pmid, .yr = year), by = "pmid") |>
  mutate(yr = suppressWarnings(as.numeric(.yr))) |>
  filter(applicable, !is.na(yr)) |>
  mutate(rep = score %in% c("partial", "full"), yr10 = (yr - 2015) / 10)

# Per-item logistic trend. Items with too few applicable studies or no variation cannot support a
# trend and are dropped rather than shown with an uninterpretable interval.
fit_one <- function(d) {
  # group_modify() requires a data frame back, so an un-fittable item returns tibble(), not NULL.
  if (nrow(d) < 50 || length(unique(d$rep)) < 2) return(tibble())
  m <- tryCatch(glm(rep ~ yr10, family = binomial, data = d), error = function(e) NULL)
  if (is.null(m) || !is.finite(coef(m)[["yr10"]])) return(tibble())
  ci <- suppressMessages(confint.default(m)["yr10", ])
  tibble(or = exp(coef(m)[["yr10"]]), lo = exp(ci[1]), hi = exp(ci[2]),
         p = summary(m)$coefficients["yr10", 4], n = nrow(d), rep_all = mean(d$rep))
}
trends <- sl |> group_by(tier_label, key, label, min_set) |> group_modify(~ fit_one(.x)) |> ungroup() |>
  filter(!is.na(or), hi < 50)                      # drop separation-driven, uninterpretable intervals

# ---- period reporting rates (the LEVELS; the trend OR alone is a ratio without a level) ---------
per_lab <- c("2005-2010", "2011-2015", "2016-2020", "2021-2026")
per_rate <- sl |>
  mutate(per = cut(yr, c(-Inf, 2010, 2015, 2020, Inf), labels = per_lab)) |>
  group_by(label, per) |>
  summarise(k = sum(rep), n = n(), r = k / n, .groups = "drop") |>
  # Wilson interval on each period proportion: the periods have very unequal n (the corpus is
  # heavily post-2016), so a bare point implies precision the early periods do not have.
  mutate(ci = purrr::map2(k, n, ~ stats::prop.test(.x, .y)$conf.int),
         lo = vapply(ci, `[`, numeric(1), 1), hi = vapply(ci, `[`, numeric(1), 2)) |>
  select(-ci)

# ---- figure: trajectories of the minimum-set covariates -------------------------------------
# Single panel, minimum set only, to stay on the primary analysis. The 34-covariate forest of trend
# ORs that used to sit above this is now the table: 34 ordered estimates with intervals read better
# as numbers, and the plot needed shrunken labels to fit at all.
dodge <- position_dodge(width = 0.32)   # 6 series x 4 periods: bare pointranges would overplot
pB <- per_rate |>
  filter(label %in% panel$label[panel$min_set]) |>
  ggplot(aes(per, r, group = label, colour = label)) +
  geom_line(linewidth = 0.55, position = dodge) +
  geom_pointrange(aes(ymin = lo, ymax = hi), size = 0.28, linewidth = 0.45, position = dodge) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1), limits = c(0, 1)) +
  scale_colour_brewer(palette = "Dark2", name = NULL) +
  labs(x = NULL, y = "Reported (partial or full)") +
  theme(legend.position = "bottom", legend.text = element_text(size = 7.5),
        legend.key.height = unit(9, "pt"), axis.text.x = element_text(size = 7.5)) +
  guides(colour = guide_legend(nrow = 3))
# AJT single-column width (fig_w1), as for the other exhibits — a six-line trajectory does not need
# the double-column plate the two-panel version occupied.
save_fig("F_item_trends", pB, width = fig_w1, height = 3.9)

write_legend("F_item_trends", paste0(
  "**Figure. Reporting of the minimum-set covariates over calendar time.** Percentage of applicable ",
  "analyzable studies reporting each of the five minimum-set covariates, partially or fully, by publication ",
  "period; vertical bars are 95% confidence intervals, and points are offset horizontally to separate them. ",
  "Per-covariate trends across the whole panel are tabulated separately. *Abbreviations:* ACR, acute ",
  "cellular rejection; AMR, antibody-mediated rejection; CLAD, chronic lung allograft dysfunction; CMV, ",
  "cytomegalovirus; HLA, human leucocyte antigen; IS, immunosuppression."))

# ---- table: period levels + trend, every covariate ---------------------------------------------
wide <- per_rate |> mutate(v = pct(r)) |> select(label, per, v) |>
  pivot_wider(names_from = per, values_from = v)
tab <- trends |> left_join(wide, by = "label") |> arrange(tier_label, desc(or)) |>
  transmute(Tier = as.character(tier_label), Covariate = ms_mark(label, min_set), N = n,
            !!per_lab[1] := .data[[per_lab[1]]], !!per_lab[2] := .data[[per_lab[2]]],
            !!per_lab[3] := .data[[per_lab[3]]], !!per_lab[4] := .data[[per_lab[4]]],
            `OR per decade` = sprintf("%.2f", or), `95% CI` = sprintf("%.2f–%.2f", lo, hi))
save_df_tbl(tab, "T_item_trends",
            caption = "Reporting of each covariate by publication period, and the trend per decade",
            footer = paste0("Percentage of applicable studies reporting each covariate (partially or ",
              "fully) by publication period, with the per-decade trend from logistic regression on ",
              "publication year, grouped by panel tier and ordered within tier by that trend. N = applicable ",
              "studies; period denominators vary. Covariates applicable ",
              "in fewer than 50 studies, or reported in all or none, are omitted. Intervals excluding 1 ",
              "indicate a trend. Partial-or-full is not era-comparable where the partial anchor encodes a ",
              "historical default: phenotyping scores partial for BOS only, which every pre-2011 study met ",
              "before RAS was described. * minimum immunological set. *Abbreviations:* ACR, acute cellular ",
              "rejection; AMR, antibody-mediated rejection; BOS, bronchiolitis obliterans syndrome; CI, ",
              "confidence interval; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; cPRA, calculated panel-reactive antibody; ",
              "CNI, ",
              "calcineurin inhibitor; D/R, donor/recipient; DBD, donation after brain death; DCD, donation after ",
              "circulatory death; DSA, donor-specific antibody; EVLP, ex-vivo lung perfusion; FEV1, forced ",
              "expiratory volume in one second; GERD, gastro-oesophageal reflux disease; HLA, human leucocyte ",
              "antigen; IS, immunosuppression; OR, odds ratio; PGD, primary graft dysfunction; RAS, restrictive ",
              "allograft syndrome."),
            group_col = "Tier")

rise <- trends |> filter(lo > 1) |> nrow(); fall <- trends |> filter(hi < 1) |> nrow()
message(sprintf("11 complete: %d items with a trend | %d rising, %d falling, %d flat.",
                nrow(trends), rise, fall, nrow(trends) - rise - fall))

# ---- phenotype reporting, three ways -----------------------------------------------------------
# Reported separately from the trend table because collapsing this item to partial-or-full turns a
# polarisation into an apparent collapse: `partial` is "BOS only, no RAS", which every pre-2011
# study met before RAS was described. The levels move in opposite directions.
ph_lab <- c(not = "No phenotype reported", partial = "BOS only", full = "BOS/RAS/mixed breakdown")
ph <- an |>
  mutate(.y = suppressWarnings(as.numeric(year)),
         per = cut(.y, c(-Inf, 2010, 2015, 2020, Inf), labels = per_lab)) |>
  filter(!is.na(per)) |>
  count(per, score_phenotyping) |>
  filter(score_phenotyping %in% names(ph_lab)) |>
  group_by(per) |> mutate(tot = sum(n), v = sprintf("%d (%s)", n, pct(n / tot))) |> ungroup() |>
  mutate(lvl = unname(ph_lab[as.character(score_phenotyping)])) |>
  select(per, lvl, v, tot) |>
  pivot_wider(names_from = lvl, values_from = v, values_fill = "0 (0%)")
ph <- ph |> transmute(Period = per, `Studies` = tot,
                      !!ph_lab[["not"]] := .data[[ph_lab[["not"]]]],
                      !!ph_lab[["partial"]] := .data[[ph_lab[["partial"]]]],
                      !!ph_lab[["full"]] := .data[[ph_lab[["full"]]]])
save_df_tbl(ph, "T_phenotyping_split",
            caption = "CLAD phenotype reporting by publication period",
            footer = paste0("Analyzable studies with a resolvable year, n (%) per period. BOS only is the ",
              "pre-2011 default: restrictive allograft syndrome was not described until 2011, so a study ",
              "reporting BOS alone met the partial anchor by construction. Collapsing these levels to ",
              "reported-or-not is therefore not comparable across eras. *Abbreviations:* BOS, bronchiolitis ",
              "obliterans syndrome; CLAD, chronic lung allograft dysfunction; RAS, restrictive allograft syndrome."))
