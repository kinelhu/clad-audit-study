# col_widths.R — recommended relative column weights for a table, derived from its own content.
#
# Vendored from the house style (~/.dotfiles/pandoc/themes/kinan/report-helpers.R) so that `analysis/`
# has NO dependency outside this repository. The analysis pipeline used to source the whole house-style
# file for this one function; everything else it needs (save_df_tbl, save_tbl, write_legend, theme_clad,
# the palettes) is already project-local. Rendering the manuscript still uses the house style, but that
# happens in publication/, which is not part of the reproducible analysis path.
#
# Keep in sync by hand if the upstream changes; it is nine lines and has been stable.

# A column counts as numeric if every non-empty cell is digits and the punctuation that decorates them
# (ranges, percents, CIs, comparison operators). Such a column cannot wrap.
NUMRE <- "^[-0-9.,%()\\[\\]<>=≥≤ /+–]+$"

.num_cols <- function(df) vapply(df, function(c) {
  v <- as.character(c); v <- v[!is.na(v) & nzchar(v)]
  length(v) > 0 && all(grepl(NUMRE, v, perl = TRUE)) }, logical(1))

# Numeric columns cannot break, so they claim their longest cell outright; text wraps, so it claims a
# fraction of its longest cell, floored by its longest unbreakable word (a header wraps between words and
# at hyphens, so "2005-2010" demands 4 characters, not 9). The cap keeps one very long label from
# swallowing the table: past ~30 characters it is wrapping regardless.
auto_col_widths <- function(df, group_col = NULL) {
  d <- if (!is.null(group_col) && group_col %in% names(df)) df[setdiff(names(df), group_col)] else df
  isnum <- .num_cols(d)
  maxc <- vapply(d, function(c) { v <- as.character(c); v <- v[!is.na(v) & nzchar(v)]
    if (length(v)) max(nchar(v)) else 1 }, numeric(1))
  hdr  <- vapply(strsplit(names(d), "[ /\n-]+"), function(w) max(nchar(w)), numeric(1))
  w <- ifelse(isnum, pmax(maxc, hdr), pmax(pmin(maxc, 30) / 1.8, hdr))
  round(w / min(w), 1)
}
