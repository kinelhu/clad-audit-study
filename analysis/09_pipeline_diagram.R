# 09_pipeline_diagram.R
# -----------------------------------------------------------------------
# Extraction / analysis pipeline schematic, rendered with Graphviz `dot`
# (native edge routing + uniform box widths) to PNG (300 dpi) + PDF, so it
# drops into both the HTML report and a LaTeX/PDF build via include_graphics.
# The two live counts (extractions, analyzable N) are injected from 00_setup.
# Requires the `dot` binary (brew install graphviz).
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

# Legend companion (like every other figure) so the report's fig_legend("F_pipeline") has a source; written
# unconditionally, independent of whether `dot` is installed to render the diagram itself.
write_legend("F_pipeline", paste0(
  "**Figure. Extraction and analysis pipeline.** The dashed box marks the two language-model steps, each ",
  "validated against a blinded expert reference standard. The abstract classifier runs on all screened records: its ",
  "study-type label gates eligibility, and its interventional flag and other fields feed the trials landscape ",
  "and the representativeness check. Colours: blue inputs and outputs, yellow deterministic steps, orange ",
  "language-model steps. Diagram rendered with Graphviz. *Abbreviations:* CLAD, chronic lung allograft ",
  "dysfunction; DOI, digital object identifier; JATS, Journal Article Tag Suite; PMID, PubMed identifier."))

dot_bin <- Sys.which("dot")
if (nzchar(dot_bin)) {
  n_extract <- nrow(af)     # extractions in the frame (corpus ∩ extractions)
  n_keep    <- nrow(an)     # analyzable after structure-based eligibility
  # Coverage of the ELIGIBLE universe, computed — the box used to carry a hardcoded "45%" from the
  # phase-1 era alongside a count of every extraction on disk, which read as 1,653 of a 1,551-study
  # universe. Both numbers were true of different things and neither was retrieval coverage.
  if (!exists("n_retr_elig")) source(file.path(dir_analysis, "_coverage.R"))

  # Palette: blue = inputs/outputs, yellow = deterministic steps, orange = LLM inference, purple = pending validation.
  dot <- sprintf('digraph pipeline {
  graph [rankdir=TB, fontname="Helvetica", nodesep=0.45, ranksep=0.55, splines=spline, bgcolor="white"]
  node  [fontname="Helvetica", fontsize=11, shape=box, style="rounded,filled", width=3.0, margin="0.20,0.13", penwidth=1.0, color="#95a5a6"]
  edge  [fontname="Helvetica", fontsize=9, color="#7f8c8d", arrowsize=0.75, penwidth=1.0]

  corpus   [label="PubMed search and screening\\n1,923 records (2005 to 2026)", fillcolor="#D6EAF8"]
  retrieve [label="Tiered full-text retrieval\\n%d of %d eligible studies (%.1f%%)", fillcolor="#FCF3CF"]
  finalize [label="Deterministic finalisation\\ngrounding, covariate-to-panel mapping,\\nminimum-set count", fillcolor="#FCF3CF"]
  eligible [label="Structure-based eligibility\\n%d analyzable studies", fillcolor="#FCF3CF"]
  analysis [label="Analysis\\ncompleteness, reported versus adjusted, trend,\\nselective reporting, analytic validity", fillcolor="#D6EAF8"]

  // The two language-model steps sit inside a dashed box marking the expert-validation scope.
  subgraph cluster_llm {
    style=dashed; color="#8e44ad"; penwidth=1.4; labelloc="t"; fontsize=10; fontcolor="#8e44ad";
    label="expert-validated";
    extract  [label="Full-text extraction (LLM)\\ngrounded passes, verbatim quote per item:\\nstudy profile, 36-item covariate panel, CLAD model\\nplus grounded covariate re-enumeration\\nfor the multivariable studies", fillcolor="#F5CBA7", penwidth=1.8]
    classify [label="Abstract classifier (LLM)\\none pass per record\\nstudy type, design, N, intervention\\nall 1,923 records", fillcolor="#F5CBA7"]
    { rank=same; extract; classify }
    extract -> classify [style=invis]
  }

  // Weighted spine keeps the backbone straight and centred.
  corpus -> retrieve [weight=10]
  retrieve -> extract [weight=10]
  extract -> finalize [weight=10]
  finalize -> eligible [weight=10]
  eligible -> analysis [weight=10]

  // The classifier is a parallel arm: it gates eligibility (study type) AND feeds the analysis
  // (authoritative interventional flag for the trials landscape; fields for the representativeness check).
  corpus   -> classify
  classify -> eligible
  classify -> analysis
}', n_retr_elig, n_eligible, 100 * n_retr_elig / n_eligible, n_keep)

  dot_file <- file.path(dir_figures, "F_pipeline.dot")
  writeLines(dot, dot_file)
  png_out <- file.path(dir_figures, "F_pipeline.png")
  pdf_out <- file.path(dir_figures, "F_pipeline.pdf")
  system2(dot_bin, c("-Tpng", "-Gdpi=300", shQuote(dot_file), "-o", shQuote(png_out)))
  system2(dot_bin, c("-Tpdf", shQuote(dot_file), "-o", shQuote(pdf_out)))
  message(sprintf("09 complete: F_pipeline.{png,pdf} rendered via dot (%d extracted -> %d analyzable).", n_extract, n_keep))
} else {
  message("09 skipped: `dot` (graphviz) not found on PATH — brew install graphviz to render F_pipeline.")
}
