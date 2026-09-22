# theme_clad.R
# -----------------------------------------------------------------------
# Figure theme + palettes for the CLAD reporting-audit — matched to the
# author's published CLAD-bibliometry house style (theme_bw base, black panel
# border, grey93 major grid only, no baked-in titles/subtitles; all descriptive
# text lives in the figure legend). Blues/RdBu palette family; signature blue
# #4393C3 (primary) + red-orange #D6604D (accent). Edit colours here only.
# -----------------------------------------------------------------------
suppressPackageStartupMessages(library(ggplot2))

# ---- signature colours ------------------------------------------------------
clad_blue <- "#4393C3"   # primary / bars
clad_red  <- "#D6604D"   # accent / lines / the "gap" or "problem"
clad_grey <- "grey70"
ok_green      <- "#009E73"   # Okabe-Ito (colourblind-safe) — pass, e.g. κ ≥ 0.6 in the validation figure
ok_vermillion <- "#D55E00"   # Okabe-Ito — flag, e.g. κ < 0.6

# ---- completeness sequential (not -> partial -> full = absent -> reported) ---
# restrained light-grey -> blue sequential (more complete = darker), not a traffic light
pal_completeness    <- c(not = "#E0E0E0", partial = "#9ECAE1", full = "#2166AC")
completeness_labels <- c(not = "Not reported", partial = "Partial", full = "Full")

# ---- reported vs adjusted (the confounding gap highlighted in accent) --------
pal_radj <- c("Not reported" = "#E0E0E0", "Reported, not adjusted" = clad_red, "Adjusted for" = clad_blue)

# ---- categorical helpers -----------------------------------------------------
pal_role   <- c(primary = "#2166AC", secondary = clad_blue, descriptor = "grey72", exclude = clad_red)
pal_source <- c(xml = clad_blue, pdf = clad_red, txt = "grey60")
pal_seq    <- c("grey96", "#C6DBEF", "#4393C3", "#084594")   # bibliometry sequential fill

# ---- theme_clad -------------------------------------------------------------
theme_clad <- function(base_size = 10, base_family = "sans") {
  theme_bw(base_size = base_size, base_family = base_family) +
    theme(
      panel.border      = element_rect(colour = "black", fill = NA, linewidth = 0.5),
      panel.grid.major  = element_line(colour = "grey93", linewidth = 0.3),
      panel.grid.minor  = element_blank(),
      axis.line         = element_blank(),
      axis.ticks        = element_line(colour = "black", linewidth = 0.35),
      axis.ticks.length = unit(0.15, "cm"),
      axis.text         = element_text(colour = "black", size = rel(0.9)),
      axis.title        = element_text(colour = "black", size = rel(0.95)),
      strip.background  = element_rect(fill = "grey95", colour = "black", linewidth = 0.4),
      strip.text        = element_text(face = "bold", size = rel(0.9)),
      legend.key.size   = unit(0.38, "cm"),
      legend.text       = element_text(size = rel(0.85)),
      legend.title      = element_text(size = rel(0.9), face = "bold"),
      legend.position   = "bottom",
      plot.tag          = element_text(face = "bold", size = rel(1.1)),
      plot.tag.position = "topleft",
      plot.margin       = margin(4, 6, 4, 6)
    )
}
theme_set(theme_clad())

# ---- publication sizing ------------------------------------------------------
# Author each figure AT its target column width so the typesetter does not rescale it — differential rescaling
# (authoring at mixed widths, then scaling all to one column) is what makes text sizes drift between figures.
# AJT/JHLT-style column widths. base_size = 10 at fig_w2 gives ~9 pt axis text; lab_size 2.6 mm ~ 7.4 pt on-plot
# labels — both above typical journal minima (~5-7 pt) at final printed size. Use fig_w1 only for a genuinely
# simple single-column figure (and re-check legibility at that size).
fig_w1 <- 3.4     # single-column width, inches (~86 mm)
fig_w2 <- 7.0     # double-column / full text width, inches (~178 mm)
lab_size <- 2.6   # on-plot value-label size, mm (~7.4 pt) — use for EVERY geom_text data/value label

# Minimum-set markers. ms_mark: plain asterisk for tables (docx/csv). ms_md: markdown
# for figure axes rendered with ggtext::element_markdown() — minimum-set covariates in
# bold deep-blue so they stand out from the rest. (The "★" glyph tofu-boxes in cairo.)
ms_mark <- function(label, is_min) ifelse(is_min, paste0(label, " *"), as.character(label))
ms_md   <- function(label, is_min) ifelse(is_min,
  paste0("<span style='color:#084594'>**", label, "**</span>"), as.character(label))
