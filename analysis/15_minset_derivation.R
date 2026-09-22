# 15_minset_derivation.R
# -----------------------------------------------------------------------
# How the five minimum-set determinants were chosen, and what was considered and not chosen.
#
# Why this exists: the Methods asserted the set rather than deriving it ("five determinants were
# selected ... named by consensus or supported by primary evidence"), which is an assertion, not a
# procedure. A reviewer's objection is never "why this item" but "why not that one", and a table
# listing only the five winners cannot answer it. Co-author review, 2026-08-31.
#
# The three admission criteria are the panel-level criteria already stated in the Methods, applied
# to the alloimmune tier: necessary to interpret a CLAD estimate, reportable at a stated granularity,
# and near-universally ascertainable in transplant practice. A determinant meeting the first two but
# not the third is a *recommended* panel item, not a minimum-set one — which is exactly the
# recommended/min_set split already encoded in panel.py, so this table documents a decision the
# instrument already carries rather than inventing one after the fact.
#
# HAND-MAINTAINED CONTENT, deliberately. Every other table in this pipeline is computed, but the
# evidence column is a reading of five papers and cannot be derived from the frame. The keys and the
# min_set/recommended flags ARE read from panel_dict.csv, so if the instrument changes and this table
# does not, the join below fails loudly rather than printing a stale rationale.
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

deriv <- tibble::tribble(
  ~key,             ~consensus,                    ~evidence,                                   ~ascertain,                                    ~status,
  "cmv_dr",         "ISHLT BOS and RAS risk factor", "Mixed: consensus designation attaches to the restrictive phenotype; null in a bronchiolitis-obliterans cohort (Luckraz 2003)", "Universal; serostatus is determined before transplantation",  "Minimum set",
  "hla_mismatch",   "ISHLT BOS and RAS risk factor", "Predisposes to BOS severity (Chalermskulrat 2003)", "Universal; every recipient is HLA typed",     "Minimum set",
  "maintenance_is", "ISHLT BOS and RAS risk factor", "Calcineurin-inhibitor choice alters BOS risk in randomized comparison (Treede 2012)", "Universal; the regimen is prescribed in every recipient", "Minimum set",
  "acr",            "ISHLT: \"perhaps the greatest risk factor\"", "Independent predictor of BOS, the oldest and strongest of the five (Burton 2009)", "Universal where surveillance or indication biopsy is performed; ISHLT A-grade is a standard scale", "Minimum set",
  "amr",            "ISHLT BOS and RAS risk factor; diagnostic criteria defined 2016", "Large adjusted hazard for CLAD (Roux 2016)", "Requires biopsy and antibody workup; the GAP definition (2026) gives a common standard", "Minimum set",
  "de_novo_dsa",    "ISHLT BOS and RAS risk factor", "De novo DQ DSA approximately double CLAD risk (Tikkanen 2016)", "Depends on a centre's antibody surveillance protocol and assay threshold", "Recommended",
  "pre_tx_dsa",     "ISHLT BOS and RAS risk factor", "Weaker and less consistent than de novo DSA", "Assay platform and positivity threshold vary between centres", "Recommended",
  "induction",      "Not designated a risk factor", "Inconsistent; no survival or BOS benefit in randomized comparison (Ailawadi 2008)", "Universal where used, but use itself varies by centre policy", "Panel, not minimum set")

# Lymphocytic bronchiolitis is named by consensus but has NO panel item, so it cannot join on a key.
# It is carried as an explicit row rather than omitted: its absence is the instrument's real gap, and
# a derivation table that quietly skipped it would be the same failure it exists to prevent.
lb <- tibble::tibble(
  Determinant = "Lymphocytic bronchiolitis (ISHLT B-grade)",
  `Consensus designation` = "ISHLT BOS risk factor",
  `Primary evidence` = "Severity predicts long-term outcome independently of A-grade rejection (Glanville 2008)",
  `Ascertainable at a stated granularity` = "Biopsy B-grading is standardised but inconsistently reported, and ungradable airway sampling is common",
  Status = "Not an item in this panel")

panel_lbl <- panel |> dplyr::select(key, label, min_set, recommended)
stopifnot(all(deriv$key %in% panel_lbl$key))          # fails loudly if the instrument moves under this table

joined <- deriv |> dplyr::left_join(panel_lbl, by = "key")
# Assert the hand-written Status against the flags the instrument actually carries, so the two cannot
# drift: a row claiming "Minimum set" for an item panel.py does not flag as min_set is a hard error.
stopifnot(identical(joined$min_set, joined$status == "Minimum set"),
          identical(joined$recommended, joined$status == "Recommended"))

tbl <- joined |>
  dplyr::transmute(
    Determinant = label,
    `Consensus designation` = consensus,
    `Primary evidence` = evidence,
    `Ascertainable at a stated granularity` = ascertain,
    Status = status) |>
  dplyr::bind_rows(lb)

save_df_tbl(tbl, "T_minset_derivation",
  caption = "Derivation of the minimum immunological set: determinants considered, and the basis for including or excluding each",
  footer = paste0(
    "Candidate determinants were drawn from the ISHLT chronic lung allograft dysfunction and bronchiolitis ",
    "obliterans syndrome consensus reports and from the field's risk-factor reviews. A determinant entered the ",
    "minimum set only if it met all three criteria: designated a bronchiolitis obliterans syndrome or restrictive ",
    "allograft syndrome risk factor by consensus, supported by primary cohort or trial evidence, and ascertainable ",
    "at a stated granularity in routine transplant practice. Determinants meeting the first two but not the third ",
    "are recommended panel items rather than minimum-set items. Evidence strength is uneven across the five and is ",
    "stated per determinant rather than summarised; the set is a judgement about which determinants matter most, ",
    "not a ranking by effect size, and no meta-analysis of chronic lung allograft dysfunction risk factors exists ",
    "from which weights could be taken. The final row records a consensus-named risk factor that this instrument ",
    "does not measure. *Abbreviations:* ACR, acute cellular rejection; AMR, antibody-mediated rejection; BOS, ",
    "bronchiolitis obliterans syndrome; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; cPRA, ",
    "calculated panel-reactive antibody; D/R, donor/recipient; DSA, donor-specific antibody; GAP, graft, antibody ",
    "and pathology; HLA, human leucocyte antigen; IS, immunosuppression; ISHLT, International Society for Heart ",
    "and Lung Transplantation; RAS, restrictive allograft syndrome."))

message(sprintf("15 complete: minimum-set derivation, %d determinants (%d minimum set, %d recommended, %d excluded, 1 unmeasured).",
                nrow(tbl), sum(deriv$status == "Minimum set"), sum(deriv$status == "Recommended"),
                sum(deriv$status == "Panel, not minimum set")))
