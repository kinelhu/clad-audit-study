# 18_grounding_sensitivity.R
# Was the quote actually in the paper? And what changes if we insist that it was?
#
# WHY. The protocol requires a supporting quote for every non-zero score and enforces its PRESENCE in
# code; it does not match the quote against the source text (S5). tools/verify_grounding.py did that
# match afterwards and wrote analysis/tables/_grounding_audit.csv, one row per quote with a verdict:
# exact, fuzzy (located above the similarity threshold), trivial (too short to mean anything) or
# unmatched. docs/grounding-verification.md read those numbers by hand. This script computes them,
# so the supplement can state the match rate and the sensitivity from one source (decision-table
# row 12, docs/peer-review-2026-09-21.md: two of six lenses led with "required is not verified").
#
# WHAT. (1) Match rates by quote source, over every item quote and over the minimum set. (2) The
# demotion sensitivity: every minimum-set score whose PROSE quote is unmatched is set to not reported,
# and the per-item non-reporting share and the none-share are recomputed. Table quotes are not
# demoted: a table quote fails substring matching when the PDF reflowed the table, which says
# nothing about whether the value is there, and the expert validation read the same tables.
# Demotion can only move completeness DOWN, so this is a one-sided bound on how much unverifiable
# grounding could have flattered the headline.

if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

min_keys <- panel$key[panel$min_set]
item_lab <- if ("label" %in% names(panel)) setNames(panel$label, panel$key) else setNames(panel$key, panel$key)

# STANDS DOWN IN THE PUBLIC TREE, and says so. The audit file is written by tools/verify_grounding.py
# from the extraction outputs, and it carries the QUOTES themselves — article text, which cannot be
# redistributed for the same reason the abstracts and full texts cannot. So it is absent from the
# public repository by design, and a script that died here would make `Rscript analysis/run_all.R`
# fail for every outside reader.
.ga_path <- file.path(dir_tables, "_grounding_audit.csv")
if (!file.exists(.ga_path)) {
  message("18 skipped: ", basename(.ga_path), " absent. It is written by tools/verify_grounding.py ",
          "from the extraction outputs, which carry article text and are not redistributable.")
} else {

ga <- read_csv(.ga_path, show_col_types = FALSE,
               col_types = readr::cols(pmid = readr::col_character(), .default = readr::col_guess())) |>
  filter(kind == "item")
stopifnot(all(c("pmid", "key", "src", "verdict") %in% names(ga)),
          all(ga$verdict %in% c("exact", "fuzzy", "trivial", "unmatched")))

an <- an |> mutate(pmid = as.character(pmid))
ga <- ga |> semi_join(an, by = "pmid")          # analyzable cohort only; the audit ran on every extraction

# ---- (1) match rates ----------------------------------------------------------------------------
rate_by_src <- function(d) d |>
  mutate(src = factor(src, levels = c("text", "table", "unspecified"))) |>
  group_by(src, .drop = FALSE) |>
  summarise(n = n(), unmatched = sum(verdict == "unmatched"), .groups = "drop") |>
  mutate(pct_unmatched = 100 * unmatched / n)
rates_all <- rate_by_src(ga)
rates_min <- rate_by_src(ga |> filter(key %in% min_keys))

# ---- (2) demotion -------------------------------------------------------------------------------
dem <- ga |> filter(key %in% min_keys, src == "text", verdict == "unmatched") |> distinct(pmid, key)
an_dem <- an
for (k in min_keys) {
  col <- paste0("score_", k)
  hit <- an_dem$pmid %in% dem$pmid[dem$key == k] & an_dem[[col]] %in% c("partial", "full")
  an_dem[[col]][hit] <- "not"
}
n_demoted <- sum(vapply(min_keys, \(k) sum(an[[paste0("score_", k)]] != an_dem[[paste0("score_", k)]], na.rm = TRUE), numeric(1)))

not_share <- function(d) {
  vapply(min_keys, \(k) { s <- d[[paste0("score_", k)]]; app <- s %in% c("not", "partial", "full")
                          100 * sum(s[app] == "not") / sum(app) }, numeric(1))
}
none_share <- function(d) 100 * mean(rowSums(across_scores(d)) == 0)
across_scores <- function(d) sapply(min_keys, \(k) d[[paste0("score_", k)]] %in% c("partial", "full"))
minset_median <- function(d) median(rowSums(across_scores(d)))

base <- not_share(an); demo <- not_share(an_dem)
quotes_min <- ga |> filter(key %in% min_keys, src == "text") |>
  group_by(key) |> summarise(n_prose = n(), unmatched = sum(verdict == "unmatched"), .groups = "drop")

tab <- tibble(key = min_keys) |>
  left_join(quotes_min, by = "key") |>
  mutate(Determinant = item_lab[key],
         `Prose quotes, n` = cm(n_prose),
         `Unmatched, n (%)` = sprintf("%d (%.1f%%)", unmatched, 100 * unmatched / n_prose),
         `Not reported, as scored` = sprintf("%.0f%%", base[key]),
         `Not reported, unmatched demoted` = sprintf("%.0f%%", demo[key]),
         `Shift, points` = sprintf("+%.1f", demo[key] - base[key])) |>
  select(-key, -n_prose, -unmatched)

save_df_tbl(tab, "T_grounding_sensitivity",
  caption = "Quote verification and the demotion sensitivity for the minimum set",
  footer = sprintf(paste0(
    "Every non-zero score carries a supporting quote whose presence is enforced in code; here each quote is ",
    "matched after the fact against the source text (case-insensitive, whitespace-normalised substring, with a ",
    "similarity fallback for reflowed lines). Over all %s item quotes in the analyzable cohort, %.1f%% of prose ",
    "quotes and %.1f%% of table quotes could not be located; the table stratum reflects PDF tables reflowed by ",
    "text extraction, not absence of the value. The sensitivity treats every minimum-set score whose prose quote ",
    "is unmatched as not reported (%s scores demoted) and recomputes non-reporting over applicable studies. ",
    "Demotion can only lower completeness, so the result is the most that unverified quotes could have added to ",
    "it: the median count is %d before and %d after, and the share reporting none of the five moves from ",
    "%.0f%% to %.0f%%."),
    cm(nrow(ga)), rates_all$pct_unmatched[rates_all$src == "text"], rates_all$pct_unmatched[rates_all$src == "table"],
    cm(n_demoted), minset_median(an), minset_median(an_dem), none_share(an), none_share(an_dem)))

readr::write_csv(tibble(
  n_quotes            = nrow(ga),
  prose_n             = rates_all$n[rates_all$src == "text"],
  prose_unmatched_pct = rates_all$pct_unmatched[rates_all$src == "text"],
  table_n             = rates_all$n[rates_all$src == "table"],
  table_unmatched_pct = rates_all$pct_unmatched[rates_all$src == "table"],
  minset_prose_unmatched_pct = rates_min$pct_unmatched[rates_min$src == "text"],
  n_demoted           = n_demoted,
  median_base         = minset_median(an),
  median_demoted      = minset_median(an_dem),
  none_base_pct       = none_share(an),
  none_demoted_pct    = none_share(an_dem),
  shift_min           = min(demo - base),
  shift_max           = max(demo - base)
), file.path(dir_tables, "_grounding_stats.csv"))

message(sprintf("grounding: prose unmatched %.1f%%, table %.1f%%; demoted %d scores; none %.0f%% -> %.0f%%; shifts %.1f to %.1f points",
                rates_all$pct_unmatched[rates_all$src == "text"], rates_all$pct_unmatched[rates_all$src == "table"],
                n_demoted, none_share(an), none_share(an_dem), min(demo - base), max(demo - base)))

}   # end of the guard on _grounding_audit.csv
