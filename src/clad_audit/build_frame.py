"""Flatten extractions/*.json → one tidy row per paper for the R analysis stage.

Joins LLM extraction with authoritative corpus metadata (era, journal, publisher, country, group_key,
design_meta, tier) and the on-disk source format (xml/pdf/txt — for the extraction-miss sensitivity).
Emits per-item score_<key> columns, per-item adj_<key> flags (covariate in the primary CLAD model),
the study/analysis/interventional fields, and composites.

    uv run python -m clad_audit.build_frame     → data/analysis_frame.csv
"""

from __future__ import annotations

import json

import pandas as pd

from .config import CORPUS_CSV, DATA_DIR, DESIGN_OVERRIDE, INTENT_OVERRIDE, registry_named
from .panel import ITEM_KEYS, ITEMS, MIN_SET

EXTRACT_DIR = DATA_DIR / "extractions"
FULLTEXT_DIR = DATA_DIR / "fulltext"
OUT = DATA_DIR / "analysis_frame.csv"
PANEL_DICT = DATA_DIR / "panel_dict.csv"


def _write_panel_anchors() -> None:
    """Emit the scoring anchors as a table so the paper can show what 'partial' and 'full' mean.

    Generated from panel.py, never hand-typed: the anchors ARE the instrument, and a hand-copied
    methods table is the first thing to drift from the codebook it documents.
    """
    pd.DataFrame([{
        "Tier": it.tier,
        "Covariate": it.label + (" *" if it.min_set else ""),
        "Not reported (0)": "not stated",
        "Partial (1)": it.partial,
        "Full (2)": it.full,
        "Scored only when": it.trigger if it.conditional else "",
    } for it in ITEMS]).to_csv(DATA_DIR / "panel_anchors.csv", index=False)


def _write_panel_dict() -> None:
    """Emit the panel as a dictionary CSV so R uses the same labels/tiers (single source = panel.py)."""
    pd.DataFrame([{
        "key": it.key, "tier": it.tier, "label": it.label,
        "min_set": it.min_set, "recommended": it.recommended,
        "conditional": it.conditional, "trigger": it.trigger,
    } for it in ITEMS]).to_csv(PANEL_DICT, index=False)

# authoritative metadata carried over from the corpus (NOT re-extracted by the LLM)
META_COLS = ["year", "era", "journal", "publisher", "country", "group_key",
             "is_multicenter_or_registry", "design_meta", "tier"]


def _source_format(pmid: str) -> str:
    for ext in ("xml", "txt", "pdf"):
        if (FULLTEXT_DIR / f"{pmid}.{ext}").exists():
            return ext
    return ""


# clean string labels so R reads scores unambiguously (avoids "NA"/None colliding with R's NA)
_SCORE_LABEL = {0: "not", 1: "partial", 2: "full", "NA": "na"}
# which items may legitimately be N/A — single-sourced from the panel, never a second list to maintain
_CONDITIONAL = {it.key: it.conditional for it in ITEMS}


def _score_label(v) -> str:
    return _SCORE_LABEL.get(v, "missing")


def main() -> None:
    routed = DATA_DIR / "corpus_routed.csv"
    meta = pd.read_csv(routed if routed.exists() else CORPUS_CSV, dtype={"pmid": str, "doi": str})
    meta = meta.set_index("pmid")

    rows = []
    for f in sorted(EXTRACT_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        pmid = d.get("pmid") or f.stem
        items = d.get("items", {})
        # Adjustment source: prefer the grounded per-item `adjusted` flag (schema v0.3+, evidence-
        # required, multivariable-only); fall back to the legacy free-list `adjustment_set` for older
        # extractions. (An earlier stopgap that pruned adjustment_set against score=="not" was reverted:
        # the test showed most contradictions were score false-negatives, not spurious adjustments — the
        # grounded schema is the real fix. See docs/decision-log.md.)
        grounded = [k for k, v in items.items()
                    if isinstance(v, dict) and "adjusted" in v and v.get("adjusted") in (True, "true")]
        if any(isinstance(v, dict) and "adjusted" in v for v in items.values()):
            adj = set(grounded)
        else:
            adj = set(d.get("adjustment_set") or [])
        eff = d.get("exposure_effect") or {}
        ana = d.get("analysis") or {}
        prov = d.get("_provenance") or {}

        row = {
            "pmid": pmid,
            "source_format": _source_format(pmid),
            # study-level
            "outcome_role": d.get("outcome_role"),
            "study_design": d.get("study_design"),
            "study_design_llm": d.get("study_design_llm"),
            "study_design_meta": d.get("study_design_meta"),
            "design_disagreement": d.get("design_disagreement"),
            "sample_size": d.get("sample_size"),
            "followup": d.get("followup"),
            "funding": d.get("funding"),
            "missing_data_handled": d.get("missing_data_handled"),
            "strobe_cited": d.get("strobe_cited"),
            # interventional / trial (CONSORT companion)
            # full-text pass value, retained as a COMPARATOR only; the authoritative is_interventional
            # is set below from the abstract classifier (grounded, stable). See docs/methods.md.
            "is_interventional_ft": d.get("is_interventional"),
            "intervention": d.get("intervention"),
            # intervention_intent: THE REPORTED intent field. Full-text intent, classified WHENEVER the exposure
            # is a therapy/procedure/protocol (incl. observational comparisons), INDEPENDENT of is_interventional
            # (prompt broadened 2026-08-09). Canonical 3-value vocab prevent_clad/treat_clad/na (treat_risk_factor
            # collapsed into prevent_clad below). CAUTION: NOT a proxy for interventional DESIGN — a non-na intent
            # does not imply a trial; use is_interventional / triangulated RCT for design. Validity via human κ.
            # Interim provenance: 50 records carry intent from the original (narrow) extraction, 80 from a targeted
            # intent re-pass under the broadened prompt; criteria coincide for interventional studies, and all
            # provenance unifies at the next full re-extraction (which emits 3 values natively).
            "intervention_intent": d.get("intervention_intent"),
            "trial_registered": d.get("trial_registered"),
            "registration_id": d.get("registration_id"),
            # exposure + effect (teeth)
            "primary_exposure": d.get("primary_exposure"),
            "exposure_measure": eff.get("measure"),
            "exposure_estimate": eff.get("estimate"),
            "exposure_ci": eff.get("ci"),
            "exposure_significant": eff.get("significant"),
            # analysis block
            "survival_method": ana.get("survival_method"),
            "time_varying_covariates": ana.get("time_varying_covariates"),
            "multiplicity_addressed": ana.get("multiplicity_addressed"),
            "n_clad_events": ana.get("n_clad_events"),
            "n_covariates_in_model": ana.get("n_covariates_in_model"),
            "events_per_variable": d.get("events_per_variable"),
            # adjustment
            "adjustment_set": ";".join(sorted(adj)),
            "n_adjusted": len(adj),
            # provenance
            "protocol": prov.get("protocol"),
            "model": prov.get("model"),
            "extracted": prov.get("extracted"),
        }
        # per-item score (not/partial/full/na/missing) + adjusted flag.
        # Only CONDITIONAL items have an N/A state — it means the triggering population is absent, and those
        # cells leave that item's denominator. An unconditional item is applicable to every study by
        # construction, so a model-returned "NA" there is an error, not a judgement, and it must not silently
        # shrink the denominator: it falls back to the conservative null (0, not reported), the same rule the
        # grounding guardrails apply elsewhere. Left uncoerced this produced denominators of 1,060-1,062 on
        # items the Methods describe as always applicable, which a reviewer read — correctly — as unexplained.
        # Survival-analysis items are conditional on the study HAVING a time-to-event analysis. The model
        # cannot see that reliably from the item alone, so the trigger is applied here from the study-level
        # survival_method: competing-risk handling and censoring rules are undefined for a study that never
        # fit a time-to-event model, and scoring them 0 there both understated the rate and produced two
        # denominators for one numerator (12% of 785 in the text vs 9% of 1,062 in the table).
        _tte = str(ana.get("survival_method") or "") in {"km_logrank", "cox_ph", "competing_risk"}
        for k in ITEM_KEYS:
            lbl = _score_label(items.get(k, {}).get("score"))
            if lbl == "na" and not _CONDITIONAL.get(k, False):
                lbl = "not"
            if k in ("competing_risk", "followup_censoring") and not _tte:
                lbl = "na"
            row[f"score_{k}"] = lbl
            row[f"adj_{k}"] = k in adj
        # Variant A HLA coalesce (deterministic bridge on v0.7 data; pending a full re-score). The retired
        # hla_dq item's anchors — partial "A/B/DR reported, DQ absent", full "DQ by locus" — and eplet/PIRCHE
        # (eplet_mm full) both mean HLA mismatch WAS reported by locus, so hla_mismatch = full. Fixes the
        # hla_dq↔hla_mismatch contradiction (13 impossible "not" + mis-graded partials). See panel.py note.
        dq = _score_label(items.get("hla_dq", {}).get("score"))
        ep = _score_label(items.get("eplet_mm", {}).get("score"))
        if dq in ("partial", "full") or ep == "full":
            row["score_hla_mismatch"] = "full"

        # --- min-set composites: computed AFTER the HLA coalesce, from the FINAL score columns -----
        # Ordering bug fixed 2026-08-12. These were computed above from the raw `items` dict, i.e. BEFORE
        # the coalesce, so a study whose hla_mismatch was upgraded to "full" kept a min-set count that
        # still counted it as not reported. 13 of 1,073 rows disagreed with their own score columns, and
        # min_set_met read False for the one study that reports all six in full. Deriving both from
        # row[f"score_{k}"] guarantees the composites and the per-item columns can never contradict.
        ms = [row[f"score_{k}"] for k in MIN_SET]
        # strict all-or-none: all minimum-set items reported IN FULL. Derived from MIN_SET (panel.py) rather
        # than read from the extraction JSON, so it tracks min-set membership changes (e.g. induction dropped
        # 2026-08-08) without a re-extraction.
        row["min_set_met"] = all(s == "full" for s in ms)
        # PRIMARY completeness metric: count of the minimum-set items REPORTED at all (partial OR full).
        # "Reported at all" is the fair minimum bar (requiring full granularity on all of them is unreasonably
        # strict) and is the exact complement of the per-item "% not reported" headline. The partial-vs-full
        # adequacy distinction is preserved per-item in the completeness landscape.
        row["n_minset"] = sum(1 for s in ms if s in ("partial", "full"))
        rows.append(row)

    df = pd.DataFrame(rows).set_index("pmid")
    # Corpus-membership guard: the analysis frame must be exactly (frozen screened corpus ∩ extractions).
    # An extraction whose pmid is not in the PRISMA-frozen corpus (e.g. a supplementary retrieval not yet
    # reconciled into corpus.csv) must NOT silently enter the analyzable cohort with NaN era/journal/design
    # metadata. Drop such orphans here (reported), not downstream. To admit one, add it to the corpus properly.
    orphans = [p for p in df.index if p not in meta.index]
    if orphans:
        print(f"  WARNING: {len(orphans)} extraction(s) not in frozen corpus — dropped: {orphans}")
        df = df.drop(index=orphans)
    df = df.join(meta[META_COLS], how="left").reset_index()

    # Design reconciliation is REDONE here rather than trusted from the extraction JSONs. finalize()
    # baked study_design in at extraction time from the design_meta of that moment, so a corrected
    # metadata rule cannot otherwise reach the frame without re-running every LLM call. Recomputing
    # from the corpus text also survives corpus_routed.csv being older than corpus.csv, which it is:
    # routing is a retrieval step and is not re-run for a metadata fix.
    _hay = (meta["title"].fillna("") + " " + meta["abstract"].fillna("")).str.lower()
    _meta_design = pd.Series(
        ["rct" if "Randomized Controlled Trial" in str(pt) else "registry" if registry_named(h) else ""
         for pt, h in zip(meta["pubtypes"], _hay)],
        index=meta.index, dtype="object")
    df["design_meta"] = df["pmid"].map(_meta_design).fillna("")
    df["study_design_meta"] = df["design_meta"]
    df["study_design"] = df["study_design_meta"].where(
        df["study_design_meta"].isin(["rct", "registry"]), df["study_design_llm"])
    # Hand-adjudicated records outrank metadata; see DESIGN_OVERRIDE for the admission rule.
    _adj = df["pmid"].map({k: v[0] for k, v in DESIGN_OVERRIDE.items()})
    df["design_adjudicated"] = _adj.notna()
    df["study_design"] = _adj.where(_adj.notna(), df["study_design"])
    df["design_disagreement"] = (df["study_design_meta"] != "") & \
                                (df["study_design_meta"] != df["study_design_llm"])
    _missing = set(DESIGN_OVERRIDE) - set(df["pmid"])
    if _missing:   # a pmid that left the corpus must not silently stop being adjudicated
        print(f"  WARNING: DESIGN_OVERRIDE pmid(s) absent from the frame: {sorted(_missing)}")
    print(f"  design reconciled: {(df['study_design_meta'] == 'registry').sum()} registry, "
          f"{(df['study_design_meta'] == 'rct').sum()} rct by metadata; "
          f"{int(df['design_disagreement'].sum())} override the model; "
          f"{int(df['design_adjudicated'].sum())} adjudicated by hand")

    # join the study classifier (species/clinical + controlled-vocab intervention class & intent)
    cls_path = DATA_DIR / "classifications.csv"
    if cls_path.exists():
        cls = pd.read_csv(cls_path, dtype={"pmid": str})
        keep = [c for c in ["pmid", "species", "clinical", "intervention_class", "intent",
                            "evaluates_intervention", "study_design", "sample_n", "study_type"] if c in cls.columns]
        cls = cls[keep].rename(columns={"intervention_class": "class_intervention", "intent": "class_intent",
                                        "study_design": "study_design_ab", "sample_n": "sample_n_ab"})
        df = df.merge(cls, on="pmid", how="left")
        # AUTHORITATIVE is_interventional = the abstract classifier's grounded evaluates_intervention (fixed rule,
        # not per-study); the full-text flag stays as is_interventional_ft, a comparator for the reliability κ.
        df["is_interventional"] = df["evaluates_intervention"].where(
            df["evaluates_intervention"].notna(), df["is_interventional_ft"])
        print(f"  joined classifier: {int((df.get('clinical') == True).sum())} clinical of {len(df)}")

        # --- normalise the interventional taxonomy (documented, auditable) --------
        # Intent: the classifier emitted two spellings for the treatment arm; unify.
        df["class_intent"] = df["class_intent"].replace(
            {"treatment_established": "treatment_established_clad"})
        # Full-text intent (the REPORTED intent field): canonical 3-value vocab prevent_clad/treat_clad/na.
        # treat_risk_factor is collapsed into prevent_clad — modifying an upstream CLAD risk factor (GERD/CMV/DSA)
        # in patients WITHOUT established CLAD is a preventive strategy, not a distinct intent; this also restores
        # parity with the abstract classifier's prevent/treat binary. (Extraction prompt emits 3 values from the
        # next full re-run; this remap keeps the current 4-value extractions consistent. 2026-08-09.)
        df["intervention_intent"] = df["intervention_intent"].replace({"treat_risk_factor": "prevent_clad"})
        # Hand-adjudicated intents outrank the extraction; see INTENT_OVERRIDE for the admission rule.
        _int_adj = df["pmid"].map({k: v[0] for k, v in INTENT_OVERRIDE.items()})
        df["intent_adjudicated"] = _int_adj.notna()
        df["intervention_intent"] = _int_adj.where(_int_adj.notna(), df["intervention_intent"])
        if set(INTENT_OVERRIDE) - set(df["pmid"]):
            print(f"  WARNING: INTENT_OVERRIDE pmid(s) absent: {sorted(set(INTENT_OVERRIDE) - set(df['pmid']))}")
        # Reassign the small "Other pharmacological"/"Not specified" residual into
        # meaningful classes by inspection of the extracted intervention text. Steroid
        # withdrawal and CNI conversions are immunosuppression-regimen strategies, not a
        # miscellany; the coping-skills trial is behavioural. Voriconazole (antifungal)
        # and cyclophosphamide (cytotoxic) remain a genuine two-study residual.
        class_remap = {
            "15823457": "IS minimization / conversion",   # steroid withdrawal
            "16386606": "IS minimization / conversion",   # steroid withdrawal
            "17889206": "IS minimization / conversion",   # ciclosporin -> tacrolimus conversion
            "30401394": "IS minimization / conversion",   # sustained-release tacrolimus conversion
            "32195326": "Behavioural / supportive",       # telephone-delivered coping-skills training
        }
        m = df["pmid"].astype(str).map(class_remap)
        df.loc[m.notna(), "class_intervention"] = m[m.notna()]

        # --- rule-based split of the RESIDUAL intervention classes -------------------------------
        # The classifier's taxonomy left three catch-all bins that carried real, separable content:
        # "Other pharmacological" (the 2nd-largest bar in the trials landscape), "Surgical / procedural"
        # (the largest, 95 studies, most of which are not surgery at all but donor-selection and
        # transplant-type comparisons), and "Other"/"Not specified". Maintenance immunosuppression, the
        # most central drug class in transplantation, had no category at all.
        #
        # Rules are SCOPED to those residual bins, never to a named class: run globally they would dissolve
        # "Inhaled ciclosporin" (an airway-targeted therapy, not systemic maintenance IS) and overwrite the
        # per-PMID class_remap above. Scoping to "Other pharmacological" ALONE was the earlier mistake — it
        # stranded equivalent studies in "Other" and "Not specified" (desensitisation with TPE/IVIG/ATG,
        # preemptive anti-dnDSA therapy, Perfadex/Celsior preservation, virtual crossmatch).
        #
        # Where `intervention` is empty the rules fall back to the TITLE. 31 of the 95 surgical studies had
        # no intervention text but perfectly classifiable titles ("Lungs from donation after circulatory
        # death donors", "Unilateral Versus Bilateral Lung Transplantation"). This makes the class depend on
        # a second field, which is why it is documented in methods.md rather than left implicit.
        # Order matters: first match wins, most specific first.
        RESIDUAL_BINS = {"Other pharmacological", "Surgical / procedural", "Other", "Not specified"}
        residual_rules = [
            ("Ex-vivo lung perfusion / preservation",
                r"\bevlp\b|ex.vivo|perfadex|celsior|preservation|organ care system|\bocs\b|retrieval timing|cold storage"),
            ("Extracorporeal support",
                r"\becmo\b|\becls\b|extracorporeal (membrane|life)|cytokine filtration|bridging"),
            ("Donor selection",
                r"\bdcd\b|\bdbd\b|donation after (circulatory|cardiac)|heart-beating|extended.{0,12}criteria|"
                r"marginal donor|acceptability criteria|donor pool|donor offer|virtual crossmatch|\babo\b|brain-dead|cardiac-dead|"
                r"hepatitis|viremic|deceased-donor|donor criteria"),
            ("Transplant type / technique",
                r"single.?lung|bilateral|double.?lung|unilateral|lobar|retransplant|\bredo\b|concomitant|urgency|heart.?lung|multi-organ|"
                r"liver.?lung|lung-liver|combined .{0,20}transplant|implantation sequence|anastomos|no-clamp|"
                r"graft resiz|size.?match|does side matter|allocation"),
            ("Airway / sinus procedure", r"sinus|douch|bronchoscopy|tracheostom|\bstent\b"),
            ("Azithromycin / macrolide", r"azithromycin|macrolide|clarithromycin"),
            ("Induction agent",          r"\bratg\b|antithymocyte|thymoglobulin|basiliximab|alemtuzumab"),
            ("Antibody / biologic",      r"belatacept|rituximab|carfilzomib|sotatercept|\bivig\b|immune globulin|"
                                        r"immunoglobulin|plasmapheresis|plasma exchange|desensiti|antibody-directed|"
                                        r"anti-?dndsa|dndsa"),
            ("Antimicrobial (non-CMV)",  r"ribavirin|voriconazole|antibiotic|pseudomonas|antifungal"),
            ("Antireflux (medical)",     r"omeprazole|proton pump|\bppi\b|histamine-2|h2 receptor|domperidone|"
                                        r"acid suppression"),
            ("Metabolic / endocrine",    r"metformin|vitamin d|pioglitazone|glp-1|gliptin|dpp-4|\bcd26\b|"
                                        r"vildagliptin|bisphosphonate|denosumab|parathyroid"),
            ("Maintenance immunosuppression",
                r"tacrolimus|cyclosporin|ciclosporin|mycophenolat|\bmmf\b|azathioprine|calcineurin|\bcni\b|"
                r"immunosuppress|methotrexate|cyclophosphamide|prednisolone|steroid|sirolimus|everolimus|\blcpt\b|"
                r"trough monitoring"),
            ("Behavioural / supportive", r"mobile health|telehealth|coping|behavioural|non-invasive ventilation|"
                                         r"\bnippv\b|rehabilitation|bilevel|\bbipap\b"),
        ]
        titles = (df["pmid"].astype(str).map(meta["title"]) if "title" in meta.columns
                  else pd.Series("", index=df.index))
        txt = (df["intervention"].fillna("").str.strip()
               .where(lambda v: v != "", titles.fillna("")).str.lower())
        # An EMPTY class_intervention is in scope ONLY for studies actually in the interventional cohort:
        # the two metadata-RCT secondary analyses carry no class and were skipped by every rule, surfacing
        # as a "Not specified" bar. Including blanks unconditionally would instead label ~1,100 
        # non-interventional studies from their titles, which is meaningless for those rows.
        _lab = df["class_intervention"].fillna("")
        _in_cohort = df["is_interventional"].isin([True, "True"]) | df["study_design"].eq("rct")
        resid = _lab.isin(RESIDUAL_BINS) | (_lab.eq("") & _in_cohort)
        was_surgical = df["class_intervention"].eq("Surgical / procedural")
        n_before = int(resid.sum())
        for label, pat in residual_rules:
            hit = resid & txt.str.contains(pat, regex=True, na=False)
            df.loc[hit, "class_intervention"] = label
            resid &= ~hit
        # Anything still unmatched: keep the fact that it WAS surgical rather than dumping it into a
        # generic bin, and mark the rest by whether any text existed to classify on.
        df.loc[resid & was_surgical, "class_intervention"] = "Surgical (other)"
        still = resid & ~was_surgical
        df.loc[still & txt.str.strip().eq(""), "class_intervention"] = "Not specified"
        df.loc[still & ~txt.str.strip().eq(""), "class_intervention"] = "Other"
        print(f"  intervention taxonomy: {n_before} residual-bin studies -> {int(resid.sum())} unresolved "
              f"after rule-based split")

        # --- unify the two inhaled-immunosuppressant classes ---------------------------------------
        # "Aerosolised / inhaled other" grouped by DELIVERY ROUTE while every other class groups by drug
        # class or purpose, so it filed inhaled tacrolimus alongside nebulised colistin and amphotericin.
        # Inhaled ciclosporin and inhaled tacrolimus are the same clinical question — locally augmented
        # immunosuppression added ON TOP of an unchanged systemic regimen, to prevent or treat BOS (the
        # trials' own phrasing: "in addition to conventional systemic immunosuppression", NEJM 16407509;
        # "locally augmented immunosuppression ... in addition to triple-drug immunosuppression", AJT
        # 34587371). Kept DISTINCT from "Maintenance immunosuppression", which asks a different question:
        # which SYSTEMIC regimen (tacrolimus vs ciclosporin, MMF vs azathioprine). The residual inhaled
        # anti-infectives stay in "Aerosolised / inhaled other".
        inhaled_is = (df["class_intervention"].eq("Inhaled ciclosporin")
                      | (df["class_intervention"].eq("Aerosolised / inhaled other")
                         & df["intervention"].fillna("").str.lower().str.contains(
                             r"tacrolimus|ciclosporin|cyclosporin", regex=True, na=False)))
        df.loc[inhaled_is, "class_intervention"] = "Inhaled immunosuppression"
        print(f"  intervention taxonomy: 'Inhaled immunosuppression' = {int(inhaled_is.sum())} studies "
              f"(inhaled ciclosporin + inhaled tacrolimus)")

    # --- adjustment from the decoupled clad_model pass (replaces the per-item grounding) ---------------
    # The per-item grounded `adjusted` flag under-counted multivariable models (~75 false negatives: it needed
    # a per-covariate multivariable quote for each of 36 items and defaulted to univariable_only under doubt).
    # clad_model.py makes ONE study-level judgment (model_type + covariate list, scoped to CLAD outcome); we map
    # its covariates to panel keys deterministically here. See docs/decision-log.md.
    cm_path = DATA_DIR / "clad_models.csv"
    if cm_path.exists():
        from .clad_model import map_covariates
        cm = pd.read_csv(cm_path, dtype={"pmid": str})
        cm = cm[["pmid", "model_type", "method", "n_covariates", "covariates"]].rename(
            columns={"method": "clad_method", "n_covariates": "n_covariates_clad", "covariates": "clad_covariates"})
        df["n_adjusted_grounded"] = df["n_adjusted"]                 # keep the old per-item count as a comparator
        df = df.merge(cm, on="pmid", how="left")

        # Prefer the grounded refine-pass covariate lists (clad_model --refine) for the multivariable studies:
        # the base pass under-enumerated table-based covariates; refine re-enumerates them at higher effort with
        # per-covariate grounding. See docs/decision-log.md.
        rf_path = DATA_DIR / "clad_covariates.csv"
        if rf_path.exists():
            rf = pd.read_csv(rf_path, dtype={"pmid": str}).set_index("pmid")["covariates"]
            repl = df["pmid"].map(rf)
            df.loc[repl.notna(), "clad_covariates"] = repl[repl.notna()]
            print(f"  refined covariates applied to {int(repl.notna().sum())} multivariable studies")

        def _adj_keys(row) -> list:
            if row.get("model_type") != "multivariable":
                return []
            return map_covariates(str(row.get("clad_covariates") or "").split(";"))

        adj = df.apply(_adj_keys, axis=1)
        df["adjustment_set"] = adj.apply(lambda ks: ";".join(ks))     # authoritative adjustment now = clad_model
        df["n_adjusted"] = adj.apply(len)
        for k in ITEM_KEYS:
            df[f"adj_{k}"] = adj.apply(lambda ks: k in ks)
        mt = df["model_type"].value_counts().to_dict()
        print(f"  clad_model adjustment joined: {mt} (multivariable studies drive reported-vs-adjusted)")

        # Emit the UNRESTRICTED canonical adjusted-covariate long table (multivariable studies) for the
        # covariate-frequency and co-adjustment (clustered heatmap) analyses. Panel keys + non-panel confounders.
        from .clad_model import CONCEPT_LABEL, canon_covariates
        ca_rows = []
        mv = df[df["model_type"] == "multivariable"]
        for pmid, cvs in zip(mv["pmid"], mv["clad_covariates"]):
            for concept in canon_covariates(str(cvs or "").split(";")):
                ca_rows.append({"pmid": pmid, "concept": concept, "label": CONCEPT_LABEL.get(concept, concept)})
        pd.DataFrame(ca_rows).to_csv(DATA_DIR / "covariate_adjust.csv", index=False)
        print(f"  wrote covariate_adjust.csv ({len(ca_rows)} concept rows over {len(mv)} multivariable studies)")

    # join citation metrics (NIH iCite: raw count + field/time-normalized RCR) if fetched
    cit_path = DATA_DIR / "citations.csv"
    if cit_path.exists():
        cit = pd.read_csv(cit_path, dtype={"pmid": str})
        keep = [c for c in ["pmid", "cite_count", "rcr", "nih_pctl", "cites_per_year"] if c in cit.columns]
        df = df.merge(cit[keep], on="pmid", how="left")
        print(f"  joined citations: {int(df['cite_count'].notna().sum())} of {len(df)} with a count")

    df.to_csv(OUT, index=False)
    _write_panel_dict()
    _write_panel_anchors()
    print(f"wrote {len(df)} rows × {df.shape[1]} cols → {OUT}")
    print(f"wrote panel dictionary ({len(ITEMS)} items) → {PANEL_DICT}")
    print(f"  analyzable (primary+secondary): {df['outcome_role'].isin(['primary','secondary']).sum()}")
    print(f"  source formats: {df['source_format'].value_counts().to_dict()}")
    print(f"  columns: {', '.join(df.columns[:12])} … (+{df.shape[1]-12} more incl score_*/adj_*)")


if __name__ == "__main__":
    main()
