# _retrieval_worklist.R  (sourced helper, not a numbered stage)
# -----------------------------------------------------------------------
# Emits the DOI/PMID worklist for the retrieval gap: records that PASS the abstract
# eligibility gate but have no full text on disk. This is the target list for any
# credentialed fetch route (Elsevier insttoken, Wiley/OUP TDM, an on-site institutional
# IP) — see docs/retrieval-status.md.
#
# Eligibility is NOT redefined here: it is `abs_gate()` from _coverage.R, the same gate
# the PRISMA flow and the eligible-universe counts use. Two distinct "missing" notions:
#   need_retrieval  — no full text file on disk  -> the fetch worklist (what this is for)
#   not in af       — not in the analysis frame  -> superset; includes texts we HAVE but
#                     that failed/never ran extraction (those need extraction, not fetching)
# Both flags are emitted so the list reconciles with n_notretr_elig in _coverage.R.
#
# Writes: data/retrieval_worklist.csv (gitignored, regenerable)
# -----------------------------------------------------------------------
if (!exists("cov_universe")) source(local({
  d <- normalizePath(getwd(), "/")
  while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d)
  file.path(d, "analysis", "_coverage.R") }))

# Full text on disk: data/fulltext/<pmid>.<ext> (JATS-XML, PDF, TEI). Stem = pmid.
.have <- tools::file_path_sans_ext(list.files(file.path(project_root, "data/fulltext")))

.routed <- readr::read_csv(file.path(project_root, "data/corpus_routed.csv"), show_col_types = FALSE) |>
  dplyr::select(pmid, doi, tier, publisher, oa_status, oa_pdf_url)

# DOI registrant prefix -> who actually controls the file. This is the operative routing key,
# NOT Unpaywall's oa_status: of the 347 records Unpaywall tiered "OA", 278 (80%) carry a
# major-paywall prefix and resolve to a publisher stub (e.g. 10.1016 -> linkinghub.elsevier.com,
# a ~2.7 KB JS redirect with no PDF). Measured 2026-08-10 — a landing-page fetcher recovered
# 0/60 because the premise "the PDF is one link away" is false for this population.
.registrant <- c("10.1016" = "Elsevier", "10.1002" = "Wiley", "10.1111" = "Wiley",
                 "10.1007" = "Springer", "10.1097" = "Wolters Kluwer", "10.1093" = "OUP",
                 "10.1183" = "ERS", "10.1164" = "ATS", "10.3390" = "MDPI", "10.1186" = "BMC",
                 "10.3389" = "Frontiers", "10.1371" = "PLOS", "10.21037" = "AME",
                 "10.1155" = "Hindawi", "10.1101" = "CSH/preprint")
reg_of <- function(doi) {
  pre <- sub("/.*$", "", ifelse(is.na(doi), "", doi))
  out <- unname(.registrant[pre]); ifelse(is.na(out), "other/unknown", out)
}

worklist <- cov_universe |>
  dplyr::filter(eligible) |>
  dplyr::left_join(.routed, by = "pmid") |>
  dplyr::mutate(on_disk = pmid %in% .have, in_frame = retrieved) |>
  dplyr::filter(!on_disk) |>
  dplyr::transmute(pmid, doi, registrant = reg_of(doi), year, era, journal, publisher,
                   tier, oa_status, oa_pdf_url, study_type, study_design, in_frame) |>
  # group by who actually controls the file, then newest first — this is the order that
  # matches how the gap has to be worked (one credential/licence conversation per registrant).
  dplyr::arrange(registrant, dplyr::desc(suppressWarnings(as.numeric(year))))

readr::write_csv(worklist, file.path(project_root, "data/retrieval_worklist.csv"))

# Bare DOI list (one per line, no header) — the form a fetch loop / probe script wants.
writeLines(worklist$doi[!is.na(worklist$doi) & nzchar(worklist$doi)],
           file.path(project_root, "data/retrieval_worklist_dois.txt"))

message(sprintf(paste0("_retrieval_worklist.R: %d abstract-eligible records need retrieval ",
                       "(%d with a DOI, %d without).\n  By registrant (the operative routing ",
                       "key): %s"),
                nrow(worklist), sum(!is.na(worklist$doi) & nzchar(worklist$doi)),
                sum(is.na(worklist$doi) | !nzchar(worklist$doi)),
                paste(sprintf("%s %d", names(sort(table(worklist$registrant), decreasing = TRUE)),
                              sort(table(worklist$registrant), decreasing = TRUE)), collapse = ", ")))
