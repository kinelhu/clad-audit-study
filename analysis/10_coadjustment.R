# 10_coadjustment.R
# -----------------------------------------------------------------------
# What do multivariable CLAD models actually adjust for, and which covariates are
# preferentially co-adjusted? Uses data/covariate_adjust.csv (canonical concepts: panel
# items + non-panel confounders age/sex/BMI/LAS/ischemic-time/comorbidity/lung-function),
# emitted by build_frame over the studies that fit a MULTIVARIABLE model for CLAD.
#   (1) unrestricted covariate-adjustment frequency table (ranked)
#   (2) co-adjustment heatmap: phi correlation, hierarchically clustered (dendrogram)
#   (3) immunological-set comprehensiveness (how many of the min-set items are co-adjusted)
# -----------------------------------------------------------------------
if (!exists("an")) source(local({ d <- normalizePath(getwd(), "/"); while (!file.exists(file.path(d, "renv.lock")) && dirname(d) != d) d <- dirname(d); file.path(d, "analysis", "00_setup.R") }))

ca_all <- read_csv(file.path(project_root, "data/covariate_adjust.csv"), show_col_types = FALSE)
mv_ids <- an |> filter(model_type == "multivariable") |> pull(pmid)
N <- length(mv_ids)
ca <- ca_all |> filter(pmid %in% mv_ids) |> distinct(pmid, concept, label)

# ---- (1) frequency table ---------------------------------------------------------------------
tier_lab <- setNames(as.character(panel$tier_label), panel$key)
demo <- c("age", "sex", "bmi", "comorbidity", "las", "ischemic_time", "lung_function")
grp_of <- function(k) if (k %in% demo) "Demographic / peri-operative" else {tl <- tier_lab[k]; if (is.na(tl)) "Other" else tl}
fam_order <- c("Demographic / peri-operative", "Case-mix / context", "Core immunological",
               "Non-alloimmune second hits", "Novel / emerging", "Outcome ascertainment", "Other")
freq <- ca |> count(concept, label, name = "n") |>
  mutate(pct = n / N, Group = factor(vapply(concept, grp_of, character(1)), levels = fam_order)) |>
  arrange(Group, desc(n))                              # family sections (show_table group_col="Group"), by frequency within
save_df_tbl(freq |> transmute(Covariate = label, Group = as.character(Group), n, `%` = pct(pct)), "T_covariate_frequency",
  caption = "Covariates adjusted for in multivariable CLAD models (unrestricted, by covariate family)",
  footer = sprintf(paste0("Among the %d analyzable studies that fit a multivariable model for CLAD. Free-text ",
    "covariates mapped to canonical concepts (panel items plus non-panel confounders); the primary exposure and ",
    "unmappable variables are excluded. %% = share of the %d studies. *Abbreviations:* ACR, acute cellular ",
    "rejection; AMR, antibody-mediated rejection; BOS, bronchiolitis obliterans syndrome; CLAD, chronic lung ",
    "allograft dysfunction; CMV, cytomegalovirus; cPRA, calculated panel-reactive antibody; D/R, donor/recipient; DBD, donation after brain ",
    "death; DCD, ",
    "donation after circulatory death; DSA, donor-specific antibody; EVLP, ex-vivo lung perfusion; FEV1, forced ",
    "expiratory volume in one second; GERD, gastro-oesophageal reflux disease; HLA, human leucocyte antigen; IS, ",
    "immunosuppression; PGD, primary graft dysfunction; RAS, restrictive allograft syndrome."), N, N),
            group_col = "Group")

# ---- (2) co-adjustment heatmap (phi correlation, hierarchically clustered) --------------------
keep <- freq |> filter(n >= 8) |> pull(concept)
present <- ca |> filter(concept %in% keep)
mat <- matrix(0L, nrow = N, ncol = length(keep), dimnames = list(mv_ids, keep))
mat[cbind(match(present$pmid, mv_ids), match(present$concept, keep))] <- 1L
C <- suppressWarnings(cor(mat))                        # phi coefficient for binary columns
hc <- hclust(as.dist(1 - C), method = "average")
# small-N robustness: how many immunological x immunological pairs are co-adjusted above chance (Fisher exact)?
imm_keys <- intersect(c("cmv_dr", "hla_mismatch", "induction", "maintenance_is", "acr", "amr",
                        "de_novo_dsa", "pgd", "cmv_events"), keep)
ii <- utils::combn(imm_keys, 2)
imm_p <- apply(ii, 2, function(pr) tryCatch(
  fisher.test(table(factor(mat[, pr[1]], 0:1), factor(mat[, pr[2]], 0:1)))$p.value, error = function(e) NA_real_))
n_imm_pairs <- ncol(ii); n_imm_sig <- sum(imm_p < 0.05, na.rm = TRUE)
# Within-family co-adjustment strength, written out so the manuscript never hardcodes these.
# phi is a CORRELATION (co-adjustment above chance given each covariate's prevalence), not an absolute
# co-adjustment rate: immunological covariates can be positively correlated here while still rarely
# being entered together, which is what T_immuno_comprehensiveness reports.
.fam_all <- vapply(colnames(C), grp_of, character(1))
.pr <- t(utils::combn(colnames(C), 2)); .phi <- apply(.pr, 1, function(q) C[q[1], q[2]])
.f1 <- .fam_all[.pr[, 1]]; .f2 <- .fam_all[.pr[, 2]]
.dc <- c("Demographic / peri-operative", "Case-mix / context")
.is_dc  <- .f1 %in% .dc & .f2 %in% .dc
.is_imm <- .f1 == "Core immunological" & .f2 == "Core immunological"
readr::write_csv(tibble::tibble(
  metric = c("phi_demo_casemix_mean", "phi_demo_casemix_pct_pos", "phi_immuno_mean",
             "phi_immuno_pct_pos", "imm_pairs_sig", "imm_pairs_total", "imm_n_covars"),
  value  = c(round(mean(.phi[.is_dc]), 2), round(100 * mean(.phi[.is_dc] > 0)),
             round(mean(.phi[.is_imm]), 2), round(100 * mean(.phi[.is_imm] > 0)),
             n_imm_sig, n_imm_pairs, length(imm_keys))),
  file.path(project_root, "data/coadjust_stats.csv"))

ordk <- colnames(C)[hc$order]
lab_map <- setNames(freq$label, freq$concept)
pos <- setNames(seq_along(ordk), ordk)
mx <- max(abs(C[upper.tri(C)]))

long <- as.data.frame(as.table(C), stringsAsFactors = FALSE) |> setNames(c("a", "b", "phi")) |>
  mutate(phi = ifelse(a == b, NA_real_, phi), x = pos[a], y = pos[b])
# family colour squares along both edges (separate colour scale, coexists with the phi fill)
fam_col <- c("Demographic / peri-operative" = "#999999", "Case-mix / context" = "#E69F00",
             "Core immunological" = "#0072B2", "Non-alloimmune second hits" = "#009E73",
             "Novel / emerging" = "#CC79A7", "Outcome ascertainment" = "#F0E442", "Other" = "grey70")
fam <- tibble(pos = seq_along(ordk), family = vapply(ordk, grp_of, character(1)))
strip <- bind_rows(transmute(fam, x = 0.3, y = pos, family), transmute(fam, x = pos, y = 0.3, family))
lim <- c(-0.1, length(ordk) + 0.5)
hm <- ggplot() +
  geom_tile(data = long, aes(x, y, fill = phi), color = "grey92") +          # full (symmetric) matrix
  geom_point(data = strip, aes(x, y, color = family), shape = 15, size = 3) +
  scale_fill_gradient2(low = "#2166AC", mid = "white", high = "#B2182B", midpoint = 0,       # red = co-adjusted
                       limits = c(-mx, mx), na.value = "grey95", name = expression(phi)) +
  scale_color_manual(values = fam_col, name = "Covariate family",
                     breaks = intersect(names(fam_col), fam$family)) +
  scale_x_continuous(breaks = seq_along(ordk), labels = lab_map[ordk], expand = c(0, 0), limits = lim) +
  scale_y_continuous(breaks = seq_along(ordk), labels = lab_map[ordk], expand = c(0, 0), limits = lim) +
  labs(x = NULL, y = NULL) +
  # 26 covariates at 45 degrees collide badly (each label's horizontal footprint is ~sqrt(2)x its text
  # height, and long names like "Pseudomonas/Aspergillus colonization" overrun several columns). At 90
  # degrees a label occupies only its line height, so it fits whatever the column count. The legend also
  # moves BELOW: on the right it consumed ~30% of the 7-inch journal width, squeezing the matrix itself.
  theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5),
        panel.grid = element_blank(), legend.position = "bottom", legend.box = "vertical",
        legend.box.just = "left", legend.margin = margin(t = 2, b = 2),
        legend.title = element_text(size = 9), legend.text = element_text(size = 8)) +
  # STACKED, not side-by-side: sharing one row with the colourbar left the family key ~3.5 in, which
  # clipped "Non-alloimmune second hits" and dropped "Outcome ascertainment" off the figure entirely.
  # Vertical boxes give the 5-level family key the full figure width across 2 rows.
  guides(fill = guide_colourbar(order = 1, barwidth = 8, barheight = 0.5, title.vjust = 0.9),
         # title ABOVE the keys: inline, "Covariate family" consumed enough of the row to clip the last
         # entry ("Core immunological") off the right edge even with the box stacked.
         color = guide_legend(order = 2, nrow = 2, byrow = TRUE, title.position = "top",
                              override.aes = list(size = 3)))
# dendrogram segments straight from hclust (no ggdendro dependency; leaf x = clustered position)
dendro_segments <- function(hc) {
  m <- hc$merge; h <- hc$height; xpos <- numeric(nrow(m) + 1); xpos[hc$order] <- seq_len(nrow(m) + 1)
  nodeX <- numeric(nrow(m)); segs <- list()
  gp <- function(ch) if (ch < 0) c(xpos[-ch], 0) else c(nodeX[ch], h[ch])
  for (k in seq_len(nrow(m))) {
    a <- gp(m[k, 1]); b <- gp(m[k, 2]); yk <- h[k]; nodeX[k] <- (a[1] + b[1]) / 2
    segs[[length(segs) + 1]] <- data.frame(x = c(a[1], b[1], a[1]), y = c(a[2], b[2], yk),
                                           xend = c(a[1], b[1], b[1]), yend = c(yk, yk, yk))
  }
  do.call(rbind, segs)
}
den <- ggplot(dendro_segments(hc)) +
  geom_segment(aes(x, y, xend = xend, yend = yend), color = "grey45", linewidth = 0.4) +
  scale_x_continuous(expand = c(0, 0), limits = lim) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.05))) + theme_void()
p_co <- den / hm + patchwork::plot_layout(heights = c(1, 9))
# Taller than the old 7.3 because the vertical x labels and the bottom legend both need vertical room,
# and because the tiles must stay near-square to read as a correlation matrix. Width stays at the
# double-column journal figure width (fig_w2); it is height, not width, that journals let you spend.
save_fig("F_coadjustment", p_co, width = fig_w2, height = 9.6)
write_legend("F_coadjustment", paste0(
  "**Figure. Co-adjustment structure of multivariable CLAD models.** Phi (φ) correlation between covariates entered ",
  "together, across the ", N, " analyzable studies that fit a multivariable CLAD model (covariates entered in ≥ 8 ",
  "studies). Blue, co-adjusted less often than expected by chance; red, more often; the diagonal is omitted. Rows ",
  "and columns are ordered by hierarchical clustering (average linkage on 1 − φ; dendrogram above), and the coloured ",
  "squares at the edges mark each covariate's family. *Abbreviations:* ACR, acute cellular rejection; AMR, ",
  "antibody-mediated rejection; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; IS, immunosuppression."))

# ---- (3) immunological-set comprehensiveness -------------------------------------------------
MINSET <- panel$key[panel$min_set & panel$key != "clad_definition"]   # the 5 immunological determinants
nimm <- ca |> filter(concept %in% MINSET) |> count(pmid) |> right_join(tibble(pmid = mv_ids), by = "pmid") |>
  mutate(n = replace_na(n, 0L))
comp <- tibble(`Immunological determinants adjusted for` = c("0", "1", "2", "3+"),
               Studies = c(sum(nimm$n == 0), sum(nimm$n == 1), sum(nimm$n == 2), sum(nimm$n >= 3))) |>
  mutate(`%` = pct(Studies / N))
save_df_tbl(comp, "T_immuno_comprehensiveness",
  caption = "How many of the five immunological determinants each multivariable CLAD model adjusts for",
  footer = sprintf(paste0("Among the %d analyzable studies with a multivariable CLAD model. The five ",
    "immunological minimum-set determinants (CMV D/R, HLA mismatch, maintenance IS, ACR, AMR); the CLAD ",
    "definition is not a covariate. *Abbreviations:* ACR, acute cellular rejection; AMR, antibody-mediated ",
    "rejection; CLAD, chronic lung allograft dysfunction; CMV, cytomegalovirus; D/R, donor/recipient; HLA, ",
    "human leucocyte antigen; IS, immunosuppression."), N))

message(sprintf("10 complete: covariate frequency (%d concepts), co-adjustment heatmap (%d covariates), comprehensiveness. N=%d.",
                nrow(freq), length(keep), N))
