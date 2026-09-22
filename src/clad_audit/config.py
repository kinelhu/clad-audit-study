"""Shared config: the locked discovery query, paths, and constants.

Paths are derived from this file's location so the pipeline is portable regardless of the
(space-containing, OneDrive) absolute path of the project.
"""

from __future__ import annotations

import re
from pathlib import Path

# project root = .../2026-08-05-clad-reporting-audit  (src/clad_audit/config.py -> parents[2])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "pubmed"          # cached efetch XML batches (gitignored)
INTERIM_DIR = DATA_DIR / "interim"             # parsed intermediate artifacts
CORPUS_CSV = DATA_DIR / "corpus.csv"           # stage-2 deliverable: the normalized study table
CORPUS_PARQUET = DATA_DIR / "corpus.parquet"

# ---- Discovery query (LOCKED 2026-08-05; PubMed E-utilities) --------------------------------
# Tested count: 3288 raw -> 2437 after type-exclusions -> 2387 English -> 1953 (2005-present).
# The outcome-role (primary/secondary/descriptor/exclude) is NOT in the query — it is tagged
# downstream by the LLM. This query only casts the recall net.
QUERY = (
    '('
    '("Lung Transplantation"[Mesh] OR "lung transplant*"[tiab] OR "lung allograft*"[tiab] '
    'OR "pulmonary transplant*"[tiab])'
    ' AND '
    '("chronic lung allograft dysfunction"[tiab] OR CLAD[tiab] '
    'OR "bronchiolitis obliterans syndrome"[tiab] OR BOS[tiab] '
    'OR "restrictive allograft syndrome"[tiab] OR "chronic rejection"[tiab] '
    'OR "chronic allograft"[tiab])'
    ' NOT (Review[pt] OR Editorial[pt] OR Comment[pt] OR Letter[pt] '
    'OR "Case Reports"[pt] OR News[pt])'
    ' AND English[lang]'
    ' AND 2005:3000[dp]'
    ')'
)

# ---- E-utilities ---------------------------------------------------------------------------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
EFETCH_BATCH = 200            # records per efetch call
SLEEP_WITH_KEY = 0.15         # seconds between calls (<10/s with an API key)
SLEEP_NO_KEY = 0.40           # <3/s without a key

# ---- Era split (2019 ISHLT CLAD consensus) -------------------------------------------------
CONSENSUS_YEAR = 2019         # year >= 2019 => "post"

# ---- Non-original pubtypes to drop at normalize (slip through as co-tagged "Journal Article") -
EXCLUDE_PUBTYPES = {
    "Video-Audio Media",           # JoVE method videos
    "Preprint",                    # unreviewed
    "Clinical Trial Protocol",     # protocol, no results
    "Published Erratum",
    "Conference Proceedings",
    "Historical Article",
    "Introductory Journal Article",
    "Retraction of Publication",
    "Retracted Publication",
}

# ---- Named-registry detection for design_meta (TIGHT — named databases only, NOT the broad
#      multicenter keywords, which would mislabel any multicenter cohort as a registry) ----------
REGISTRY_DB = [
    "unos", "optn", "srtr", "eurotransplant",
    "united network for organ sharing", "organ procurement and transplantation network",
    "scientific registry of transplant recipients", "ishlt thoracic transplant registry",
    "national health service blood and transplant",
]

# Match these as WORDS, never as substrings. `"unos" in text` is true of every abstract containing
# "immUNOSuppression" — and of "immunosorbent", "immunosuppressive", "immunostaining". Substring
# containment labelled 138 of 174 registry-stratum studies from a word they merely happened to
# contain, overrode the model's reading of design for 125 of them, and inverted the registry
# result: genuine registry analyses report maintenance immunosuppression in 19% of cases, the
# false positives in 84%, because the word that created the stratum is the determinant it was
# then credited with reporting. Found 2026-08-31 while hand-checking design reclassifications.
_REGISTRY_DB_RE = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(k) for k in REGISTRY_DB), re.I)


def registry_named(text: str) -> bool:
    """True when `text` names one of REGISTRY_DB as a whole word."""
    return bool(_REGISTRY_DB_RE.search(text or ""))


# ---- Adjudicated design overrides (the LAST word, above metadata) --------------------------
# PubMed's "Randomized Controlled Trial" publication type is authoritative for design and stays so.
# It does, however, tag a small number of records whose own abstract states a different design in
# explicit words. Where the article contradicts the tag outright, the article wins.
#
# ADMISSION RULE, so this table cannot become a place to put studies we dislike: the article must
# name its own design in words that leave no reading in which it is randomized ("we conducted a
# prospective observational study"), and the quote that decides it is recorded here. A secondary,
# post hoc, pharmacokinetic or long-term analysis OF a randomized cohort is NOT admitted — those
# are trial results as the field counts them, and they stay RCT (PMIDs 26372728, 29087035, 31673366
# are the current examples). Each entry is one hand-read abstract, not a rule.
DESIGN_OVERRIDE = {
    "20558084": ("prospective_cohort",
                 "We conducted a prospective observational study of this protocol"),
    "25447575": ("retrospective_cohort",
                 "A retrospective observational study was conducted on all lung transplantations"),
    "26168736": ("retrospective_cohort",
                 "categorized in a study group ... and a matched control group, both groups while "
                 "already being on azithromycin treatment"),
}

# Same admission rule, for intervention_intent. Only where the article states the trial's own
# population in words that rule out the recorded intent. One entry: the everolimus/azathioprine
# IL-17 airway-biopsy substudy was recorded as treatment of established CLAD because it analyses
# biopsies from recipients who had BOS, but the randomized intervention was maintenance
# immunosuppression given to BOS-free patients, which is prevention.
INTENT_OVERRIDE = {
    "17613395": ("prevent_clad",
                 "This sub-study, from a larger, prospective clinical ERL vs AZA randomized, "
                 "controlled trial ... 213 BOS-free maintenance patients (parent trial)"),
}

# ---- Multicenter / registry detection (metadata heuristic, stage 2) ------------------------
REGISTRY_KEYWORDS = [
    "registry", "unos", "optn", "srtr", "ishlt", "eurotransplant", "uk transplant",
    "multicenter", "multicentre", "multi-center", "multi-centre", "nationwide",
    "national cohort", "collaborative", "consortium",
]
