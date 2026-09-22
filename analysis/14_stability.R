# 14_stability.R
# -----------------------------------------------------------------------
# Extraction stability: run-to-run repeatability and reasoning-effort sensitivity.
# Reads data/reextract/comparison.csv (tools/reextract_effort.py — a seeded 150-paper
# sample re-scored twice: once at the original settings, once at high reasoning effort)
# and emits the supplement's agreement table plus the inline values.
#
# Two peer-review points, one exhibit: the primary pass ran at the LOWEST effort setting,
# and it ran ONCE with no test-retest. See docs/extraction-stability.md for the reasoning.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

.cmp_path <- file.path(project_root, "data/reextract/comparison.csv")
if (!file.exists(.cmp_path)) {
  message("14 skipped: data/reextract/comparison.csv absent (run tools/reextract_effort.py)")
} else {

cmp <- read_csv(.cmp_path, show_col_types = FALSE) |>
  mutate(reported_orig = orig > 0, reported_new = new > 0)

n_papers_stab <- n_distinct(cmp$pmid)

# Overall agreement per arm. `repeat` = identical settings, so its disagreement IS the noise floor;
# `high` is only interpretable against it.
arm <- cmp |>
  group_by(variant) |>
  summarise(n = n(),
            identical = sum(orig == new),
            pct_identical = 100 * mean(orig == new),
            gained = sum(!reported_orig & reported_new),
            lost   = sum(reported_orig & !reported_new),
            .groups = "drop")

# Per-item agreement, minimum set first — the items that carry the headline.
lab <- setNames(panel$label, panel$key)
item_tab <- cmp |>
  group_by(Item = as.character(lab[key]), variant) |>
  summarise(pct = 100 * mean(orig == new), .groups = "drop") |>
  pivot_wider(names_from = variant, values_from = pct) |>
  mutate(across(where(is.numeric), ~ sprintf("%.0f%%", .x))) |>
  filter(!is.na(Item)) |>
  arrange(Item)
ms_lab <- as.character(lab[min_set_keys])
item_tab <- item_tab |>
  mutate(Set = if_else(Item %in% ms_lab, "Minimum immunological set", "Remainder of the panel")) |>
  arrange(factor(Set, levels = c("Minimum immunological set", "Remainder of the panel")), Item) |>
  select(Set, Item, `Repeat run` = `repeat`, `High reasoning effort` = high)

save_df_tbl(item_tab, "T_stability",
  caption = "Agreement of a re-scored sample with the original extraction",
  footer = sprintf(paste0("Percentage of item scores identical to the original extraction, over a seeded ",
    "random sample of %s analyzable studies re-scored twice: once at the original settings (repeat run) ",
    "and once at high reasoning effort. The repeat run measures run-to-run variation alone, since nothing ",
    "but the random seed differs; it is the reference against which the effort column should be read. ",
    "Scores are the 0/1/2 anchors; agreement is exact. *Abbreviations:* ACR, acute cellular rejection; ",
    "AMR, antibody-mediated rejection; CMV, cytomegalovirus; CNI, calcineurin inhibitor; cPRA, calculated ",
    "panel-reactive antibody; CYP3A5, cytochrome P450 3A5; D/R, donor/recipient; DSA, donor-specific ",
    "antibody; GERD, gastro-oesophageal reflux disease; HLA, human leucocyte antigen; IS, ",
    "immunosuppression; PGD, primary graft dysfunction."), cm(n_papers_stab)),
  group_col = "Set")

# McNemar on the minimum-set items: does either arm find MORE reporting than the original?
mcn <- cmp |>
  filter(key %in% min_set_keys) |>
  group_by(variant) |>
  summarise(gained = sum(!reported_orig & reported_new),
            lost   = sum(reported_orig & !reported_new),
            p = stats::mcnemar.test(matrix(c(0, sum(!reported_orig & reported_new),
                                             sum(reported_orig & !reported_new), 0), 2))$p.value,
            .groups = "drop")

# "reported none of the five" per paper, original vs re-run, per arm.
none_shift <- cmp |>
  filter(key %in% min_set_keys) |>
  group_by(variant, pmid) |>
  summarise(o = sum(reported_orig), n = sum(reported_new), .groups = "drop_last") |>
  summarise(pct_none_orig = 100 * mean(o == 0), pct_none_new = 100 * mean(n == 0), .groups = "drop")

stats <- arm |>
  select(variant, pct_identical) |>
  pivot_wider(names_from = variant, values_from = pct_identical,
              names_prefix = "pct_identical_") |>
  bind_cols(mcn |> select(variant, gained, lost, p) |>
              pivot_wider(names_from = variant, values_from = c(gained, lost, p))) |>
  bind_cols(none_shift |> select(variant, pct_none_new) |>
              pivot_wider(names_from = variant, values_from = pct_none_new, names_prefix = "none_")) |>
  mutate(n_papers = n_papers_stab,
         pct_none_orig = none_shift$pct_none_orig[1])
write_csv(stats, file.path(dir_tables, "_stability_stats.csv"))

message(sprintf("14 complete: %d papers | repeat %.1f%% identical, high %.1f%% | min-set net %+d (high), %+d (repeat)",
                n_papers_stab, stats$pct_identical_repeat, stats$pct_identical_high,
                mcn$gained[mcn$variant == "high"] - mcn$lost[mcn$variant == "high"],
                mcn$gained[mcn$variant == "repeat"] - mcn$lost[mcn$variant == "repeat"]))
}
