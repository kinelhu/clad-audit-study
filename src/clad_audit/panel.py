"""The locked covariate panel as structured data — single source of truth for the extraction
prompt, the scoring, and the analysis. Mirrors docs/scoring-codebook.md (LOCKED 2026-08-05).

Each item: key, tier (A-E), label, anchors for scores 1 (partial) and 2 (full), and — for
conditional items — the applicability trigger (score N/A when absent). `min_set` marks the
minimum immunological reporting set. The set holds five items. Induction was removed on 2026-08-08 and
the CLAD definition on 2026-08-13; the CLAD definition is an outcome-ascertainment item and is reported
separately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    tier: str
    label: str
    partial: str          # what a score of 1 looks like
    full: str             # what a score of 2 (full) looks like
    conditional: bool = False
    trigger: str = ""     # population that makes a conditional item applicable
    min_set: bool = False
    recommended: bool = False  # tracked but NOT required for the min-set binary


ITEMS: list[Item] = [
    # A. Case-mix / context (core)
    Item("indication_mix", "A", "Indication / diagnosis mix", "narrative only, no n", "n or % per indication"),
    Item("procedure", "A", "Single vs bilateral", "stated mixed, no split", "n/% single vs bilateral"),
    Item("era", "A", "Era / accrual window", "single year only", "explicit start–end transplant dates"),
    Item("center_structure", "A", "Center structure", "'multicenter', unquantified", "n centers (or single-center stated)"),
    Item("sample_followup", "A", "Sample size & follow-up", "sample size n reported, OR median FU without dispersion", "n AND median FU with dispersion (IQR/range)"),
    Item("donor_type", "A", "Donor type DBD/DCD", "DCD mentioned, no n", "n/% DBD vs DCD"),
    Item("evlp", "A", "EVLP use", "mentioned, no n", "n/% EVLP (or explicitly none)"),
    Item("race_ethnicity", "A", "Race / ethnicity", "one group noted / 'predominantly white'", "distribution by race/ethnicity category with n/%", recommended=True),
    # B. Core immunological (core)
    Item("cmv_dr", "B", "CMV D/R serostatus", "recipient-only / 'high-risk n'", "D/R matrix (D+/R−, D+/R+, D−/R+, D−/R−) with ns", min_set=True),
    Item("hla_mismatch", "B", "HLA mismatch", "overall/total antigen-mismatch count only (e.g. mean n/6), or a qualitative HLA-matching statement", "mismatch reported by locus (≥ A, B, DR); DQ/DP or eplet/molecular detail credited but not required. NB: recipient sensitization (cPRA/PRA) is NOT mismatch — it belongs to pre_tx_dsa", min_set=True),
    Item("pre_tx_dsa", "B", "Pre-tx DSA / cPRA", "'sensitized included'", "cPRA/PRA distribution or DSA n + MFI/spec", recommended=True),
    Item("de_novo_dsa", "B", "De novo DSA", "mentioned, no incidence", "incidence + timing/def (±MFI)", recommended=True),
    Item("induction", "B", "Induction regimen", "'induction used'", "agent(s) + n/% (or none)"),  # dropped from min-set 2026-08-08: weakest determinant evidence (no ISHLT-consensus risk-factor designation; single-centre/confounded) and its confounding role is subsumed by maintenance_is. Still scored as a covariate.
    Item("maintenance_is", "B", "Maintenance IS", "'standard triple therapy'", "CNI type + antimetabolite + steroid ±mTOR, n/% (dosing NOT required)", min_set=True),
    Item("acr", "B", "ACR burden", "'treated for rejection'", "A-grade distribution or ≥A1/A2 rate/freq", min_set=True),
    Item("amr", "B", "AMR", "mentioned as possible", "defined + incidence (pAMR/criteria)", min_set=True),  # min-set 2026-08-07 (immunological; replaced PGD)
    # C. Non-alloimmune second hits (core, CLAD-specific)
    Item("pgd", "C", "PGD grade", "'PGD occurred'", "PGD grade (ISHLT) distribution / grade-3 rate"),  # dropped from min-set 2026-08-07: a CLAD risk factor but NOT immunological (ischemia-reperfusion)
    Item("cmv_events", "C", "CMV infection/disease events", "'CMV occurred', no def", "events with def (viremia vs disease) + n"),
    Item("resp_viral", "C", "Respiratory viral infections", "mentioned", "n/rate ± organisms/method"),
    Item("colonization", "C", "Pseudomonas/Aspergillus colonization", "one organism mentioned", "organism-specific n/rate + def"),
    Item("gerd", "C", "GERD / aspiration", "mentioned", "n/rate ± dx method or fundoplication n"),
    Item("azithromycin", "C", "Azithromycin", "'some received'", "n/% + indication (prophylaxis vs CLAD-triggered)", recommended=True),
    # D. Novel / underappreciated (mostly conditional — headline tier)
    # hla_dq RETIRED (2026-08-06): DQ mismatch is part of HLA-compatibility completeness, not a distinct
    # novel marker, and its anchors encoded A/B/DR reporting → contradicted hla_mismatch. Folded into
    # hla_mismatch ("full" now credits DQ/eplet detail). Its signal is still used by build_frame to coalesce
    # hla_mismatch on the existing v0.7 extractions (deterministic bridge, pending a full re-score).
    Item("telomere", "D", "Telomere length / workup", "risk acknowledged, no data", "telomere length/flow-FISH or TERT/TERC/RTEL1 status for relevant n", conditional=True, trigger="fibrotic-ILD/IPF recipients present"),
    Item("pre_tx_is", "D", "Pre-tx immunosuppression exposure", "'some on prednisone' narrative", "pre-tx corticosteroid/DMARD exposure quantified", conditional=True, trigger="CTD-ILD/IPF/sarcoid present"),
    Item("antifibrotic", "D", "Antifibrotic exposure", "mentioned", "pirfenidone/nintedanib n + timing to tx", conditional=True, trigger="IPF/PF recipients present"),
    Item("cni_ipv", "D", "CNI intra-patient variability", "troughs reported, no variability metric", "IPV metric (CV%/SD) computed", conditional=True, trigger="CNI-level scope"),
    Item("cyp3a5", "D", "CYP3A5 pharmacogenomics", "genotyping mentioned", "CYP3A5 expressor status + n", conditional=True, trigger="PGx substudy scope"),
    Item("nonhla_ab", "D", "Non-HLA antibodies", "mentioned/tested, no results", "specific non-HLA Ab (anti-AT1R / anti-Kα1-tubulin / anti-collagen-V / MICA) tested + result/n", recommended=True),
    Item("eplet_mm", "D", "Eplet / molecular HLA mismatch", "mentioned", "eplet load / PIRCHE-II reported (value or n)", conditional=True, trigger="HLA typing reported", recommended=True),
    # E. Outcome ascertainment (light)
    Item("clad_definition", "E", "CLAD definition", "'CLAD' used, no criteria", "explicit criteria (2019 ISHLT vs BOS-only vs other) + FEV1 threshold"),  # removed from the min-set 2026-08-13: outcome ascertainment, not an immunological determinant
    Item("phenotyping", "E", "Phenotyping (BOS/RAS/mixed)", "BOS only, no RAS", "phenotype breakdown reported"),
    Item("nrad_exclusion", "E", "Reversible/azithromycin-responsive dysfunction excluded", "reversibility mentioned", "explicit exclusion of azithromycin-responsive / reversible allograft dysfunction before CLAD diagnosis"),
    Item("clad_staging", "E", "CLAD severity staging", "presence only", "CLAD stage reported (2019 consensus stage 1-4 / severity grading)"),
    Item("baseline_fev1", "E", "Baseline FEV1 method", "'baseline FEV1' undefined", "mean of the two best post-operative values ≥3 weeks apart, or the definition used"),
    Item("competing_risk", "E", "Death as competing risk", "mentioned censoring", "competing-risk method (or explicit justification)", conditional=True, trigger="time-to-event analysis of CLAD"),
    Item("followup_censoring", "E", "Follow-up / censoring", "median only", "censoring rule + FU completeness", conditional=True, trigger="time-to-event analysis of CLAD"),
]

MIN_SET = [i.key for i in ITEMS if i.min_set]           # the five immunological determinants
ITEM_KEYS = [i.key for i in ITEMS]
