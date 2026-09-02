# run_all.R
# Run the full CLAD reporting-audit analysis pipeline.
# Each script sources 00_setup.R itself (hardcoded path), so they run independently too.
# Rebuild the input frame first if extractions changed:  uv run python -m clad_audit.build_frame
#
# Env: renv (Homebrew R 4.6.1). First-time setup:  renv::init()  then  renv::restore()

project_root <- local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); d })
dir_a <- file.path(project_root, "analysis")

source(file.path(dir_a, "00_setup.R"))

scripts <- c(
  "01_completeness_landscape.R", # headline: per-item not/partial/full among analyzable
  "02_corpus_flow.R",            # corpus Table 1 + PRISMA-style flow
  "03_interpretability.R",       # interpretability index + minimum-set, by outcome role × era
  "04_reported_vs_adjusted.R",   # confounding-control axis: reported but not adjusted-for
  "05_selective_reporting.R",    # bias probe: does completeness predict significance (exploratory)
  "06_trials_landscape.R",       # interventional studies by class/intent/registration (Cravedi companion)
  "07_sensitivity.R",            # source-format (XML vs PDF) extraction-bias + author-group ICC
  "08_kappa.R",                  # validation gate: LLM–human weighted κ (no-ops until coders fill sheets)
  "09_pipeline_diagram.R",       # Methods Figure: extraction/analysis pipeline schematic (Graphviz dot)
  "10_coadjustment.R",           # covariate frequency + co-adjustment clustered heatmap + comprehensiveness
  "11_item_trends.R",            # per-item reporting over calendar time (the composite null hides divergent trends)
  "12_prisma.R",                 # PRISMA 2020 checklist; fails loudly if an item lost its location
  "13_export_figures.R",         # submission figures; keeps Figure1-5 in step with the analysis
  "14_stability.R",              # re-scored-sample agreement; skips cleanly if the sample is absent
  "15_minset_derivation.R",      # how the five were chosen, and what was considered and not chosen
  "16_trials_detail.R"           # every RCT report: comparator + report type (hand-extracted, see header)
)

for (s in scripts) {
  message("\n========== ", s, " ==========")
  source(file.path(dir_a, s))
}
message("\nPipeline complete. Tables -> analysis/tables/, figures -> analysis/figures/")
