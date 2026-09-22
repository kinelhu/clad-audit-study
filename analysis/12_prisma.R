# 12_prisma.R
# -----------------------------------------------------------------------
# PRISMA 2020 checklist as a generated exhibit.
#
# The item text is the official wording (PRISMA 2020, Table 1); the "Reported in" column is ours. Kept as
# a tracked CSV rather than typed into the .Rmd for the same reason the footnotes are: it is a curated
# record that has to be reviewable and versioned, and it is displayed in more than one place.
#
# Locations name SECTIONS, not pages. Page numbers shift with every render and would be wrong within a
# day; section names are stable and PRISMA accepts either.
#
# "Not applicable" is used deliberately and always with a reason. This is a meta-research reporting audit:
# it pools no effect estimates, so risk-of-bias appraisal of the included studies, effect measures per
# study, and certainty rating have no referent. Marking those as N/A with the reason stated is the honest
# answer; claiming them would be worse than leaving them blank.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

suppressPackageStartupMessages(library(yaml))   # items 25-27 are resolved against title-page.yml, below

pc <- read_csv(file.path(project_root, "data/prisma_checklist.csv"), show_col_types = FALSE)

# Cohort size is written {n_ana} in the checklist CSV and substituted here. It used to be typed, and it
# went stale the moment the cohort changed: three trial protocol papers left on 2026-08-31 and item 17
# still said 1,063 while every computed exhibit said 1,060. Any count quoted in that file must be a token.
pc <- pc |> mutate(across(where(is.character), ~ str_replace_all(.x, fixed("{n_ana}"), cm(nrow(an)))))
if (any(unlist(lapply(pc[sapply(pc, is.character)],
                      \(v) str_detect(replace_na(v, ""), "\\{[a-z_]+\\}")))))
  stop("12_prisma: unsubstituted {token} left in the checklist", call. = FALSE)

# Every PRISMA 2020 item must be present and must say where it is reported. A checklist with a silent gap
# is worse than none: the reader assumes the item was considered.
# Listed literally: assembling it from ranges is how 23a-d went missing from the check itself.
expected <- c("1", "2", "3", "4", "5", "6", "7", "8", "9", "10a", "10b", "11", "12",
              "13a", "13b", "13c", "13d", "13e", "13f", "14", "15", "16a", "16b", "17", "18", "19",
              "20a", "20b", "20c", "20d", "21", "22", "23a", "23b", "23c", "23d",
              "24a", "24b", "24c", "25", "26", "27")
missing  <- setdiff(expected, pc$item)
if (length(missing))
  stop(sprintf("12_prisma: checklist items absent: %s", paste(missing, collapse = ", ")), call. = FALSE)
if (any(!nzchar(trimws(pc$location))))
  stop(sprintf("12_prisma: no location given for item(s): %s",
               paste(pc$item[!nzchar(trimws(pc$location))], collapse = ", ")), call. = FALSE)

# Items 25-27 are title-page apparatus generated from title-page.yml, so whether they are still owed is READ
# FROM THAT FILE rather than from a hand-maintained note: a note saying "OUTSTANDING" survives the field
# being filled, and the checklist would keep declaring a completed item incomplete (and vice versa, which
# is the dangerous direction). A field counts as written when it exists and does not begin with TODO.
.yml <- file.path(project_root, "publication/manuscript/title-page.yml")
.owed <- c("25" = "funding", "26" = "competing_interests", "27" = "data_availability")
# This is the one script coupled to the manuscript tree, which the public analysis repository does not
# ship. Skip cleanly there rather than failing the run: the checklist describes where each item sits in
# a manuscript, so it is not meaningful without one. Same pattern as 08_kappa.R without coding sheets.
if (!file.exists(file.path(project_root, "publication/_title_page.R"))) {
  message("12_prisma.R: no publication/ tree — the PRISMA checklist is manuscript apparatus. Skipping.")
} else {
# Sourced, not reimplemented: _title_page.R parses title-page.yml for the title page and owns stmt_written(),
# so the checklist and the rendered manuscript agree by construction on what counts as finished.
source(file.path(project_root, "publication/_title_page.R"))
owed_items <- if (has_authors) names(Filter(Negate(stmt_written), .owed)) else names(.owed)
# Written, rendering, but still holding a placeholder identifier. Tracked apart from "owed": the statement
# reads as complete in the document, so this list is the only thing that stops a placeholder shipping.
prov_items <- if (has_authors) names(Filter(stmt_provisional, .owed)) else character(0)
prov_items <- setdiff(prov_items, owed_items)

# THE NOTES IN THIS TABLE ARE READ BY REVIEWERS. They said "generated from
# publication/manuscript/title-page.yml", which is a path inside this repository printed in a
# supplementary table of a submitted manuscript. It tells a reader nothing and tells them we were not
# reading our own supplement. Where the statement lives in the DOCUMENT is the answer; the file it is
# generated from is a fact about our build.
#
# The provenance is not lost: `Reported in` already says "Title page", and the machinery is described
# in the methods. Caught by check_manuscript.py, which scans the rendered text for source paths.
pc <- pc |> mutate(note = case_when(
  !item %in% names(.owed) ~ note,
  item %in% owed_items ~ "OUTSTANDING until the corresponding title-page statement is written.",
  item %in% prov_items ~ paste("Stated on the title page.",
                               "Data are offered on request; no repository deposit has been made."),
  .default = "Stated on the title page."))
todo <- pc |> filter(item %in% owed_items)

# Machine-readable sidecar for tools/check_manuscript.py, whose checklist arms read `item`, `text`,
# `location` and `note`: every item located, and every item's text present in the rendered supplement.
readr::write_csv(pc |> select(item, text, location, note), file.path(dir_tables, "_prisma_checklist.csv"))

tab <- pc |>
  transmute(Section = section, `Item` = item, `Checklist item` = text,
            `Reported in` = location,
            Notes = str_remove(note, "^OUTSTANDING - "))

save_df_tbl(tab, "T_prisma",
            caption = "PRISMA 2020 checklist",
            footer = paste0("Item text is the official PRISMA 2020 wording. Locations name sections rather ",
              "than pages, which shift between renders. Items marked not applicable are those with no ",
              "referent in a reporting audit that pools no effect estimates: appraisal of risk of bias in ",
              "the included studies, per-study effect measures, and certainty of evidence. The review was ",
              "not registered; the instrument was nonetheless locked before extraction, and its anchors are ",
              "reproduced in the supplement. *Abbreviations:* CLAD, chronic lung allograft dysfunction; DSA, ",
              "donor-specific antibody; GRADE, Grading of Recommendations Assessment, Development and ",
              "Evaluation; PRISMA, Preferred Reporting Items for Systematic reviews and Meta-Analyses."),
            group_col = "Section", landscape = TRUE)

message(sprintf("12 complete: PRISMA checklist, %d items | %d not applicable | %d still owed%s%s",
                nrow(pc), sum(pc$location == "Not applicable"), nrow(todo),
                if (nrow(todo)) paste0(" (", paste(todo$item, collapse = ", "), ")") else "",
                if (length(prov_items))
                  sprintf(" | %d PROVISIONAL, on-request wording pending a deposit (%s)",
                          length(prov_items), paste(prov_items, collapse = ", ")) else ""))
}
