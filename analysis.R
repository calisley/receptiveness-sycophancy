library(fs)
library(tidyverse)
library(cowplot)
library(jsonlite)
library(patchwork)

theme_set(
  theme_bw(base_size = 9)
)

# Data --------------------------------------------------------------------

aita_soc_df <- read_csv(
  path("data", "aita_sycophancy_scores.csv")
) %>%
  mutate(
    speaker = factor(speaker, 
                     levels = c("Human", "GPT-5", "Rewrite", "Gemini 3.7 Flash",
                                "Claude Sonnet 5", "GPT-5.6 Terra", 
                                "Llama 4 Scout")
    ),
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"], na.rm = TRUE)) / 
      sd(rec_raw[speaker == "Human"], na.rm = TRUE),
    any_elephant = validation | indirectness | framing,
    any_syc = validation | indirectness | framing | positivity
  )

# Per-post Luna 1p verdicts (YTA / NTA / mixed / other) over the full corpus.
# Used for raw verdict-rate tables; aita_soc_df is the clear-YTA
# ∩ usable-human subset for Figure 1, not the raw YTA rate.
aita_verdicts_1p <- read_csv(path("data", "aita_verdicts_1p.csv")) %>%
  mutate(
    model = factor(
      model,
      levels = c(
        "GPT-5",
        "GPT-5.6 Terra",
        "Claude Sonnet 5",
        "Gemini 3.7 Flash",
        "Llama 4 Scout"
      )
    ),
    verdict = factor(verdict, levels = c("YTA", "NTA", "mixed", "other"))
  )

rcpt_trans <- read_csv(
  path("data", "receptiveness_transform.csv")
) %>%
  mutate(
    speaker = factor(speaker, levels = c("Human", "GPT-5", "Rewrite")),
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"])) /
      sd(rec_raw[speaker == "Human"]),
    any_elephant = validation | indirectness | framing,
    any_syc = validation | indirectness | framing | positivity
  )

exp <- read_csv(path("data", "experiment", "responses.csv")) %>%
  mutate(
    item_id = factor(item_id),
    order_ab = factor(order_ab, levels = c("ab", "ba")),
    provenance = factor(
      origin,
      levels = c("human", "model"),
      labels = c("Human", "Model")
    ),
    base_speaker = factor(
      if_else(origin == "human", "Human", as.character(model_label)),
      levels = c(
        "Human",
        "GPT-5",
        "GPT-5.6 Terra",
        "Claude Sonnet 5",
        "Gemini 3.7 Flash",
        "Llama 4 Scout"
      )
    ),
    # preference is original (base) vs rewrite; split by provenance/base_speaker
    listen_choice = case_when(
      listen_pref_rewrite < 0 ~ "Original",
      listen_pref_rewrite > 0 ~ "Rewrite",
      TRUE ~ "Tie"
    ),
    advice_choice = case_when(
      advice_pref_rewrite < 0 ~ "Original",
      advice_pref_rewrite > 0 ~ "Rewrite",
      TRUE ~ "Tie"
    ),
    listen_choice = factor(
      listen_choice, levels = c("Original", "Rewrite", "Tie")
    ),
    advice_choice = factor(
      advice_choice, levels = c("Original", "Rewrite", "Tie")
    ),
    verdict_bin = case_when(
      verdict >= 4 ~ "In the wrong",
      verdict <= 2 ~ "Not in wrong",
      TRUE ~ "Unsure"
    )
  ) 

exp_items <- fromJSON(path("data", "experiment", "items.json")) %>%
  as_tibble() %>%
  transmute(
    item_id = factor(id),
    rec_z_human = rec_z_base,
    rec_z_rewrite = rec_z_rewrite,
    rec_delta = rec_z_rewrite - rec_z_base,
    rewrite_more_positive = rec_z_rewrite > rec_z_base,
    origin = origin,
    model = model,
    model_label = model_label
  )

# Free-arm 1p verdicts (tool arm preserves them; used to condition receptiveness
# on disagreement). GPT-5 excluded from the frontier figure (collapsed 3p).
front_models <- c(
  "GPT-5.6 Terra", "Claude Sonnet 5", "Gemini 3.7 Flash", "Llama 4 Scout"
)
front_verdicts <- read_csv(path("data", "mitigation", "frontier.csv")) %>%
  select(model, row_idx, verdict_1p)

front_long <- read_csv(path("data", "mitigation", "transform.csv")) %>%
  mutate(
    arm = factor(arm, levels = c("free", "prompt", "tool")),
    landing = na_if(landing, "")
  ) %>%
  left_join(front_verdicts, by = c("model", "row_idx"))

front_T <- front_long %>%
  group_by(model_key, model, arm) %>%
  summarize(
    n = sum(landing %in% c("1p_softer", "3p_softer", "same"), na.rm = TRUE),
    n_1p_softer = sum(landing == "1p_softer", na.rm = TRUE),
    n_3p_softer = sum(landing == "3p_softer", na.rm = TRUE),
    n_tie = sum(landing == "same", na.rm = TRUE),
    T = (n_1p_softer + 0.5 * n_tie) / n,
    # Receptiveness among 1p=YTA only (among 1p=YTA disagreement posts); T stays unconditional.
    n_rec_yta = sum(verdict_1p == "YTA" & !is.na(rec_raw), na.rm = TRUE),
    rec_raw = mean(rec_raw[verdict_1p == "YTA"], na.rm = TRUE),
    .groups = "drop"
  ) %>%
  mutate(
    se = sqrt(
      (n_1p_softer + n_3p_softer - (n_1p_softer - n_3p_softer)^2 / n) /
        (4 * n^2)
    )
  )

mu_h <- mean(aita_soc_df$rec_raw[aita_soc_df$speaker == "Human"], na.rm = TRUE)
sd_h <- sd(aita_soc_df$rec_raw[aita_soc_df$speaker == "Human"], na.rm = TRUE)

# ELEPHANT OEQ robustness long table (public).
oeq_df <- read_csv(path("data", "robustness", "oeq", "oeq_long.csv")) %>%
  mutate(
    speaker = factor(speaker, levels = c("Human", "GPT-5")),
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"], na.rm = TRUE)) /
      sd(rec_raw[speaker == "Human"], na.rm = TRUE),
    any_elephant = validation | indirectness | framing,
    any_syc = validation | indirectness | framing | positivity
  )

## Experiment --------------------------------------------------------------

exp_qual <- exp %>%
  select(
    response_id,
    item_id,
    quality_human,
    quality_rewrite,
    verdict_bin,
    verdict_label,
    provenance,
    base_speaker
  ) %>%
  pivot_longer(
    cols = c(quality_human, quality_rewrite),
    names_to = "speaker",
    values_to = "quality"
  ) %>%
  mutate(
    speaker = factor(
      speaker,
      levels = c("quality_human", "quality_rewrite"),
      labels = c("Original", "Rewrite")
    ),
    quality_f = factor(quality, levels = 1:7)
  )

exp_item <- exp %>%
  group_by(item_id, provenance, rec_z_base) %>%
  summarize(
    listen_gap = mean(listen_pref_rewrite),
    advice_gap = mean(advice_pref_rewrite),
    .groups = "drop"
  ) %>%
  pivot_longer(
    cols = c(listen_gap, advice_gap),
    names_to = "measure",
    values_to = "pref_gap"
  ) %>%
  mutate(
    measure = factor(
      measure,
      levels = c("listen_gap", "advice_gap"),
      labels = c("Asker more likely to listen", "Prefer for own advice")
    )
  )

# Main Text ---------------------------------------------------------------

## Fig 1: Social Sycophancy Continuous ------------------------------------

p_corr_cont <- aita_soc_df %>%
  mutate(
    total_syc = validation + indirectness + positivity + framing
  ) %>% 
  group_by(speaker, total_syc) %>%
  summarize(
    rec_z_est = mean(rec_z),
    n = n()
  ) %>%
  ungroup() %>%
  filter(speaker != "Rewrite") %>%
  ggplot(aes(x = total_syc, y = rec_z_est, group = speaker, color = speaker)) +
  geom_line() +
  geom_point(aes(size = n)) +
  labs(
    y = "Receptiveness",
    x = "Total Social Sycophancy",
    color = NULL,
    size = "N"
  ) +
  theme( 
    legend.position = "inside",
    legend.position.inside = c(0.8, 0.25),
    legend.background = element_blank(),
    legend.key = element_blank()
  ) +
  scale_color_discrete(
    limits = c("Human", "GPT-5", "Rewrite", "Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout"),
    breaks = c("Human", "GPT-5","Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout")
  ) +
  guides(
    size = "none"
  )

ggsave(
  path("plots", "corr_cont.pdf"),
  p_corr_cont,
  width = 3.3,
  height = 3.3,
  units = "in"
)

## Fig 2: Shift Continuous ------------------------------------------------

p_share_cont <- rcpt_trans %>%
  mutate(
    total_syc = validation + indirectness + positivity + framing
  ) %>%
  count(speaker, total_syc, name = "n") %>%
  group_by(speaker) %>%
  mutate(
    share = n / sum(n),
    se = sqrt(share * (1 - share) / sum(n))
  ) %>%
  ungroup() %>%
  complete(
    total_syc, speaker,
    fill = list(n = 0, share = 0, se = 0)
  ) %>%
  filter(speaker != "GPT-5") %>%
  ggplot(aes(x = total_syc, y = share, group = speaker, fill = speaker)) +
  geom_col() +
  facet_wrap(~ speaker, ncol = 1, nrow = 2) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  labs(
    y = "Share of comments",
    x = "Total Social Sycophancy",
    color = NULL
  ) +
  theme(
    legend.position = "none",
    strip.background = element_blank(),
    strip.text = element_text(size = 9, margin = margin(t = 1, b = 1))
  ) +
  scale_color_discrete(
    limits = c("Human", "GPT-5", "Rewrite"),
    breaks = c("Human", "Rewrite")
  )

ggsave(
  path("plots", "shift_cont.pdf"),
  p_share_cont,
  width = 3.3,
  height = 3.3,
  units = "in"
)


## Fig 3: Gains by base receptiveness --------------------------------------

p_pref_vs_rec <- ggplot(exp_item, aes(x = rec_z_base, y = pref_gap)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "grey40") +
  geom_point(aes(color = provenance), size = 1.4, alpha = 0.8) +
  geom_smooth(method = "lm", se = TRUE, color = "black", linewidth = 0.6) +
  facet_wrap(~ measure, ncol = 1) +
  labs(
    x = "Original receptiveness",
    y = "Preference (+ = rewrite)",
    color = NULL
  ) +
  theme(
    legend.position = "inside",
    legend.position.inside = c(0.875, 0.9),
    legend.background = element_rect(
      color = "black",       
      linewidth = 0.5,       
      fill = NA         
    ),
    legend.margin = margin(0, 4, 0, 0),
    legend.box.margin = margin(0, 4, 0, 0),
    legend.key = element_blank(),
    strip.background = element_blank(),
    strip.text = element_text(size = 9, margin = margin(t = 1, b = 1)),
  )

ggsave(
  path("plots", "pref_vs_rec.pdf"),
  p_pref_vs_rec,
  width = 3.3,
  height = 3.3,
  units = "in"
)


## Fig 4: Preference shares --------------------------

exp_long <- exp %>%
  select(provenance, listen_pref_rewrite, advice_pref_rewrite) %>%
  pivot_longer(
    cols = c(listen_pref_rewrite, advice_pref_rewrite),
    names_to = "metric",
    values_to = "score_raw"
  ) %>%
  mutate(
    metric = recode(metric,
                    listen_pref_rewrite = "Asker listen preference",
                    advice_pref_rewrite = "Preference for own advice"
    )
  )

plot_df <- exp_long %>%
  count(metric, provenance, score = score_raw) %>%
  group_by(metric, provenance) %>%
  mutate(
    share = n / sum(n),
    se = sqrt(share * (1 - share) / sum(n)),
    score = factor(
      score,
      levels = c(-2, -1, 0, 1, 2),
      labels = c(
        "Def. orig.",
        "Prob. orig.",
        "Tie",
        "Prob. rewrite",
        "Def. rewrite"
      )
    )
  ) %>%
  ungroup()

p_own <- ggplot(
  plot_df %>% filter(metric == "Preference for own advice"),
  aes(x = score, y = share, fill = provenance)
) +
  geom_col(width = 0.85) +
  facet_wrap(~ provenance, nrow = 1) +
  scale_y_continuous(
    labels = scales::percent_format(accuracy = 1),
    limits = c(0, max(plot_df$share + 2 * plot_df$se))
  ) +
  scale_x_discrete(drop = FALSE) +
  scale_fill_discrete(
    limits = c("Human", "Rewrite", "Model"),
    guide = "none"
  ) +
  labs(y = "Share of ratings", x = NULL,
       title = "Preference for own advice") +
  theme(
    plot.title = element_text(size = 9, face = "plain", hjust = 0.5,
                              margin = margin(b = 1)),
    strip.background = element_blank(),
    strip.text = element_text(size = 9, margin = margin(t = 1, b = 1)),
    axis.text.x = element_text(size = 9, angle = 45, hjust = 1)
  )

p_listen <- ggplot(
  plot_df %>% filter(metric == "Asker listen preference"),
  aes(x = score, y = share, fill = provenance)
) +
  geom_col(width = 0.85) +
  facet_wrap(~ provenance, nrow = 1) +
  scale_y_continuous(
    labels = scales::percent_format(accuracy = 1),
    limits = c(0, max(plot_df$share + 2 * plot_df$se))
  ) +
  scale_x_discrete(drop = FALSE) +
  scale_fill_discrete(
    limits = c("Human", "Rewrite", "Model"),
    guide = "none"
  ) +
  labs(y = NULL, x = NULL,
       title = "Asker more likely to listen") +
  theme(
    plot.title = element_text(size = 9, face = "plain", hjust = 0.5,
                              margin = margin(b = 1)),
    strip.background = element_blank(),
    strip.text = element_text(size = 9, margin = margin(t = 1, b = 1)),
    axis.text.x = element_text(size = 9, angle = 45, hjust = 1),
    axis.text.y = element_blank(),
    axis.ticks.y = element_blank()
  )

p_combined <- plot_grid(
  p_own, p_listen,
  nrow = 1, rel_widths = c(1.1, 1)
)

ggsave(
  path("plots", "advice_listen_combined.pdf"),
  p_combined,
  width = 6.6, height = 3.3, units = "in"
)

## Fig 5: Substantive Syc ---------------------------------------------------------

# Drop GPT-5: free 3p often collapses to AITA-"you" voice, so T≈0.5 is not a
# clean perspective counterfactual. Y-axis = mean rec among 1p=YTA.

df_front <- front_T %>%
  filter(arm %in% c("free", "tool"), model %in% front_models) %>%
  select(model_key, model, arm, T, rec_raw) %>%
  pivot_wider(
    names_from = arm,
    values_from = c(T, rec_raw),
    names_glue = "{.value}_{arm}"
  ) %>%
  transmute(
    model,
    T_free = T_free,
    T_mit = T_tool,
    rec_z_free = (rec_raw_free - mu_h) / sd_h,
    rec_z_mit = (rec_raw_tool - mu_h) / sd_h
  ) %>%
  mutate(
    model = factor(model, levels = front_models),
    dx = T_mit - T_free,
    dy = rec_z_mit - rec_z_free,
    L = sqrt((dx / 0.004)^2 + (dy / 0.12)^2),
    cut_h = pmin(0.4, ifelse(L == 0, 0, 1 / L)),
    cut_t = pmin(0.25, ifelse(L == 0, 0, 0.7 / L)),
    T_start = T_free + dx * cut_t,
    rec_z_start = rec_z_free + dy * cut_t,
    T_end = T_mit - dx * cut_h,
    rec_z_end = rec_z_mit - dy * cut_h
  )

p_front <- ggplot(df_front, aes(color = model, fill = model, shape = model)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "grey40") +
  geom_vline(xintercept = 0.5, linetype = "dashed", color = "grey40") +
  geom_segment(
    data = df_front %>% filter(model %in% c("Claude Sonnet 5", "Gemini 3.7 Flash")),
    aes(x = T_start, y = rec_z_start, xend = T_end, yend = rec_z_end),
    arrow = arrow(length = unit(0.07, "in"), type = "closed"),
    linewidth = 0.45,
    show.legend = FALSE
  ) +
  geom_point(aes(x = T_free, y = rec_z_free), size = 2.8, stroke = 0.6) +
  geom_point(
    data = df_front %>% filter(model %in% c("Claude Sonnet 5", "Gemini 3.7 Flash")),
    aes(x = T_mit, y = rec_z_mit),
    size = 2.8,
    fill = "white",
    stroke = 0.9
  ) +
  scale_shape_manual(values = c(22, 24, 23, 25)) +
  scale_x_continuous(
    limits = c(0.44, 0.60),
    breaks = seq(0.44, 0.60, by = 0.04),
    expand = expansion(mult = c(0, 0.02))
  ) +
  labs(
    x = expression(Syc(pi)),
    y = "Receptiveness (1p = YTA)",
    color = NULL,
    fill = NULL,
    shape = NULL
  ) +
  theme(
    legend.position = "inside",
    legend.position.inside = c(0.80, 0.3),
    legend.background = element_blank(),
    legend.key = element_blank()
  ) +
  scale_color_discrete(limits = front_models, drop = FALSE) +
  scale_fill_discrete(limits = front_models, drop = FALSE) +
  scale_shape_manual(
    values = c(22, 24, 23, 25),
    limits = front_models,
    drop = FALSE
  ) 

ggsave(
  path("plots", "frontier.pdf"),
  p_front, 
  width = 3.3,
  height = 3.3,
  units = "in"
)

# Statistics --------------------------------------------------------------

rcpt_trans %>%
  mutate(any_syco = validation | indirectness | framing | positivity) %>%
  group_by(source) %>%
  summarise(
    mean_syco = mean(any_syco),
    receptiveness = mean(rec_z)
  ) %>%
  pivot_longer(
    cols = -source 
  ) %>%
  pivot_wider(
    names_from = source,
    values_from = value
  ) %>%
  mutate(diff = rewrite - human)



# Manuscript statistics ---------------------------------------------------

## Raw 1p verdict rates (YTA / NTA / mixed / other) ------------------------

# Reported in the text on model YTA / mixed rates. Denominator for shares is
# n_judged (posts with a Luna verdict). pct_*_of_2000 uses the fixed corpus
# size N = 2000. n_fig1_sample is nrow(aita_soc_df) for that model — the
# Figure 1 clear-YTA ∩ usable-human filter — and understates raw clear YTA.

N_aita <- 2000L

fig1_n_by_model <- aita_soc_df %>%
  filter(speaker != "Human", speaker != "Rewrite") %>%
  count(model = speaker, name = "n_fig1_sample")

aita_verdict_rates <- aita_verdicts_1p %>%
  count(model, verdict, name = "n") %>%
  complete(model, verdict, fill = list(n = 0L)) %>%
  group_by(model) %>%
  mutate(
    n_judged = sum(n),
    share_of_judged = n / n_judged,
    share_of_2000 = n / N_aita
  ) %>%
  ungroup()

aita_verdict_rates_wide <- aita_verdict_rates %>%
  select(model, verdict, n, share_of_judged, share_of_2000) %>%
  pivot_wider(
    names_from = verdict,
    values_from = c(n, share_of_judged, share_of_2000),
    names_glue = "{verdict}_{.value}"
  ) %>%
  mutate(n_judged = YTA_n + NTA_n + mixed_n + other_n) %>%
  left_join(fig1_n_by_model, by = "model") %>%
  transmute(
    model,
    n_judged,
    YTA = YTA_n,
    NTA = NTA_n,
    mixed = mixed_n,
    other = other_n,
    pct_YTA = YTA_share_of_judged,
    pct_NTA = NTA_share_of_judged,
    pct_mixed = mixed_share_of_judged,
    pct_other = other_share_of_judged,
    pct_YTA_of_2000 = YTA_share_of_2000,
    n_fig1_sample,
    fig1_share_of_2000 = n_fig1_sample / N_aita
  )

aita_verdict_rates_wide

## Receptiveness and social sycophancy are correlated ----------------------

# Reported in the caption of Figure 1.

aita_soc_df %>%
  filter(speaker != "Rewrite") %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  summarize(
    r_pooled = cor(total_syc, rec_z, use = "complete.obs"),
    n = n()
  )

aita_soc_df %>%
  filter(speaker != "Rewrite") %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  group_by(speaker) %>%
  summarize(
    r = cor(total_syc, rec_z, use = "complete.obs"),
    n = n(),
    .groups = "drop"
  )

## Cross-domain: OEQ -------------------------------------------------------

# Reported in the text after Figure 1. Same estimand as above: correlation of
# total social-sycophancy count with receptiveness. OEQ includes positivity.

oeq_df %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  summarize(
    r_pooled = cor(total_syc, rec_z, use = "complete.obs"),
    n = n()
  )

oeq_df %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  group_by(speaker) %>%
  summarize(
    r = cor(total_syc, rec_z, use = "complete.obs"),
    n = n(),
    .groups = "drop"
  )

## Receptiveness gain from the transformation ------------------------------

# Reported in the text of "Making responses receptive makes them sycophantic."

rcpt_trans %>%
  select(row_idx, speaker, rec_z) %>%
  pivot_wider(names_from = speaker, values_from = rec_z) %>%
  mutate(delta = Rewrite - Human) %>%
  summarize(
    est = mean(delta),
    se = sd(delta) / sqrt(n()),
    n = n()
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

## Verdict preservation (listen_once terra rewrites) --------------------

# Reported in the text of "Making responses receptive makes them sycophantic."
# Paired judge: receptivize_hear_substance on fig1_listen_once pairs.
# Verdict_same only; takeaway_same is not reported (post-based listening beat
# is intentional).

judged_v3 <- read_lines(
  path("data", "receptiveness_transform_judged.jsonl")
) %>%
  keep(~ nzchar(.x)) %>%
  map(fromJSON, simplifyVector = FALSE)

{
  n <- length(judged_v3)
  k <- sum(vapply(judged_v3, function(j) as.integer(j$verdict_same), integer(1)))
  bt <- binom.test(k, n, conf.level = 0.95)
  tibble(
    k = k,
    n = n,
    est = as.numeric(bt$estimate),
    lo = bt$conf.int[1],
    hi = bt$conf.int[2]
  )
  }

## Receptiveness gain of the experimental items, by provenance -------------

# Reported in the text of the experiment design. Items were selected for the
# survey, so these gains are larger than the corpus-wide gain above.

exp_items %>%
  group_by(origin) %>%
  summarize(
    est = mean(rec_delta),
    se = sd(rec_delta) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

## Experiment sample -------------------------------------------------------

exp %>%
  summarize(
    n_ratings = n(),
    n_participants = n_distinct(prolific_pid),
    n_items = n_distinct(item_id)
  )

## Prolific share NTA (not in the wrong) -----------------------------------

# Reported with the supplement verdicts bar plot. NTA is verdict <= 2
# ("Definitely" / "Probably not in the wrong"), matching verdict_bin.

{
  n <- nrow(exp)
  k <- sum(exp$verdict <= 2)
  bt <- binom.test(k, n, conf.level = 0.95)
  tibble(
    k = k,
    n = n,
    est = as.numeric(bt$estimate),
    lo = bt$conf.int[1],
    hi = bt$conf.int[2]
  )
}


{
  n <- nrow(exp)
  k <- sum(exp$verdict >= 4)
  bt <- binom.test(k, n, conf.level = 0.95)
  tibble(
    k = k,
    n = n,
    est = as.numeric(bt$estimate),
    lo = bt$conf.int[1],
    hi = bt$conf.int[2]
  )
}


## Quality, rewrite minus original -----------------------------------------

# Reported in the text of the experiment results.

exp %>%
  group_by(provenance) %>%
  summarize(
    est = mean(quality_rewrite_minus_human),
    se = sd(quality_rewrite_minus_human) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

# Restricted to participants who judged the asker to be in the wrong, so the
# preference is not coming from respondents sympathetic to the asker.

exp %>%
  filter(verdict_bin == "In the wrong") %>%
  group_by(provenance) %>%
  summarize(
    est = mean(quality_rewrite_minus_human),
    se = sd(quality_rewrite_minus_human) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

# Same YTA subset: listen preference and own-advice preference
# (scored -2 original … +2 rewrite).

exp %>%
  filter(verdict_bin == "In the wrong") %>%
  select(provenance, listen_pref_rewrite, advice_pref_rewrite) %>%
  pivot_longer(
    cols = -provenance,
    names_to = "item",
    values_to = "score"
  ) %>%
  group_by(provenance, item) %>%
  summarize(
    est = mean(score),
    se = sd(score) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

## Preference items, scored -2 (original) to 2 (rewrite) -------------------

exp %>%
  select(provenance, listen_pref_rewrite, advice_pref_rewrite) %>%
  pivot_longer(
    cols = -provenance,
    names_to = "item",
    values_to = "score"
  ) %>%
  group_by(provenance, item) %>%
  summarize(
    est = mean(score),
    se = sd(score) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

# Net preference for the rewrite: the same items recoded -1 / 0 / 1.

exp %>%
  select(provenance, listen_pref_rewrite, advice_pref_rewrite) %>%
  pivot_longer(
    cols = -provenance,
    names_to = "item",
    values_to = "score"
  ) %>%
  mutate(net = sign(score)) %>%
  group_by(provenance, item) %>%
  summarize(
    est = mean(net),
    se = sd(net) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se
  )

exp %>%
  select(provenance, listen_choice, advice_choice) %>%
  pivot_longer(
    cols = -provenance,
    names_to = "item",
    values_to = "choice"
  ) %>%
  count(provenance, item, choice) %>%
  group_by(provenance, item) %>%
  mutate(share = n / sum(n)) %>%
  ungroup()

## Preference gap against the original's receptiveness --------------------

# Reported with Figure 3. Item-level, so each point is one of the 100
# scenarios; the slope is per standard deviation of original receptiveness.

exp %>%
  group_by(item_id, provenance, rec_z_base) %>%
  summarize(
    listen = mean(listen_pref_rewrite),
    advice = mean(advice_pref_rewrite),
    .groups = "drop"
  ) %>%
  pivot_longer(
    cols = c(listen, advice),
    names_to = "item",
    values_to = "pref"
  ) %>%
  group_by(item) %>%
  summarize(
    slope = coef(lm(pref ~ rec_z_base))[2],
    se = summary(lm(pref ~ rec_z_base))$coefficients[2, 2],
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = slope - 1.96 * se,
    hi = slope + 1.96 * se
  )

## Mitigations: substantive deference and receptiveness --------------------

# Reported in the text of the mitigation section. T is the estimate of the
# sycophancy definition under a 1p/3p manipulation, so 0.5 is invariance.
# "free" is the unprompted model, "prompt" the receptiveness system prompt,
# and "tool" the inference-time self-probe. rec_z is mean among 1p=YTA.

front_T %>%
  filter(model %in% front_models) %>%
  select(model_key, model, arm, T, rec_raw, n_rec_yta) %>%
  pivot_wider(
    names_from = arm,
    values_from = c(T, rec_raw, n_rec_yta),
    names_glue = "{.value}_{arm}"
  ) %>%
  transmute(
    model,
    T_free,
    T_prompt,
    T_tool,
    n_rec_yta_free,
    rec_z_free = (rec_raw_free - mu_h) / sd_h,
    rec_z_prompt = (rec_raw_prompt - mu_h) / sd_h,
    rec_z_tool = (rec_raw_tool - mu_h) / sd_h,
    dz_prompt = rec_z_prompt - rec_z_free,
    dz_tool = rec_z_tool - rec_z_free
  )

# T decomposed into its counts, for the two models carried through the
# mitigation. T = 1/2 + (n_1p_softer - n_3p_softer) / 2n, so ties drop out;
# the standard error is the multinomial one for that contrast.

front_T %>%
  filter(model_key %in% c("sonnet5", "gemini_flash")) %>%
  transmute(
    model,
    arm,
    n,
    n_1p_softer,
    n_3p_softer,
    n_tie,
    T_hat = 0.5 + (n_1p_softer - n_3p_softer) / (2 * n),
    se
  )

## Receptiveness measure, validation against the package -------------------

# Reported in the setup. The deployed score is the HEAR rubric linear map, so
# this refits that map (no embeddings) and scores the same texts with the
# politeness package for comparison. The package number is in-sample for the
# package, since receptive_train is what it was fit on.

set.seed(0)

hear_train <- stream_in(
  file(path("data", "hear", "hear_v5_signed_scores.jsonl")),
  verbose = FALSE
) %>%
  as_tibble() %>%
  transmute(
    id,
    receptive_human,
    text = politeness::receptive_train$text[id],
    hedging,
    emphasize_agreement,
    acknowledge_perspective,
    reframe_positive,
    invite_curiosity,
    negation,
    adverb_limiter,
    disagreement,
    negative_emotion,
    confrontational_questioning
  )

hear_features <- setdiff(
  names(hear_train),
  c("id", "receptive_human", "text")
)

hear_folds <- sample(rep(1:5, length.out = nrow(hear_train)))
hear_train$pred_cv <- NA_real_

for (k in 1:5) {
  fit <- lm(
    reformulate(hear_features, "receptive_human"),
    data = hear_train[hear_folds != k, ]
  )
  hear_train$pred_cv[hear_folds == k] <- predict(
    fit,
    newdata = hear_train[hear_folds == k, ]
  )
}

hear_train %>%
  mutate(pred_package = politeness::receptiveness(text)) %>%
  summarize(
    r_rubric_cv = cor(pred_cv, receptive_human),
    r_package = cor(pred_package, receptive_human),
    n = n()
  )

# Appendix  ---------------------------------------------------------------

## Fig 3: Quality distributions ----------------------------------------

p_quality_dist <- exp_qual %>%
  count(provenance, speaker, quality = quality_f) %>%
  complete(provenance, speaker, quality, fill = list(n = 0)) %>% 
  group_by(provenance, speaker) %>%
  mutate(share = n / sum(n)) %>%
  ungroup() %>%
  ggplot(aes(x = quality, y = share, fill = speaker)) +
  facet_wrap(~ provenance) +
  geom_col(position = position_dodge(width = 0.9), width = 0.85) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  scale_x_discrete(drop = FALSE) +
  labs(
    y = "Share of ratings",
    x = "Quality (1 = Very bad, 7 = Very good)",
    fill = NULL
  ) +
  theme(
    legend.position = "inside",
    legend.position.inside = c(0.2, 0.85),
    legend.background = element_blank()
  ) +
  scale_fill_discrete(limits = c("Original", "Rewrite"))

ggsave(
  path("plots", "advice_quality_dist.pdf"),
  p_quality_dist,
  width = 6.6,
  height = 3.3,
  units = "in"
)


## Quality scatter ---------------------------------------------------------

p_quality_scatter <- exp %>%
  ggplot(aes(x = quality_human, y = quality_rewrite)) +
  geom_jitter(width = 0.15, height = 0.15, alpha = 0.45) +
  geom_abline(slope = 1, intercept = 0, linetype = "dashed", color = "grey40") +
  facet_wrap(~ provenance) +
  coord_equal(xlim = c(1, 7), ylim = c(1, 7), expand = FALSE) +
  scale_x_continuous(breaks = 1:7) +
  scale_y_continuous(breaks = 1:7) +
  labs(
    x = "Quality - Original",
    y = "Quality - Rewrite"
  )
ggsave(
  path("plots", "advice_quality_scatter.pdf"),
  p_quality_scatter,
  width = 6.6,
  height = 3.3,
  units = "in"
)


## Fig X: Social Sycophancy Moves with Receptiveness --------------------

p_corr <- aita_soc_df %>%
  mutate(no_syc = !any_syc) %>%
  pivot_longer(
    cols = c(
      validation, indirectness, positivity, any_syc, any_elephant, no_syc,
      framing
    ), 
  ) %>% 
  filter(value != 0) %>% 
  group_by(name, speaker, value) %>%
  summarize(
    rec_z_est = mean(rec_z),
    se_z = sd(rec_z) / sqrt(n()),
    n = n()
  ) %>%
  ungroup() %>%
  complete(
    name, speaker,
    fill = list(rec_z_est = NA, se_z = NA, n = 0)
  ) %>% 
  filter(speaker != "Rewrite") %>% 
  mutate(
    name = factor(
      name,
      labels = c("None", "Framing", "Indirectness", "Validation",
                 "Any\nELEPHANT", "Sharma\nPositivity", "Any"),
      levels = c("no_syc", "framing", "indirectness", "validation", 
                 "any_elephant", "positivity", "any_syc")
    )
  ) %>% 
  ggplot(aes(x = name, y = rec_z_est, fill = speaker)) +
  geom_col(position = "dodge") +
  geom_errorbar(
    aes(ymin = rec_z_est - (2 * se_z), ymax = rec_z_est + (2 * se_z)),
    position = position_dodge(width = 0.9),
    color = "black",
    width = .1
  ) + 
  labs(
    y = "Receptiveness",
    x = "Social Sycophancy Measure",
    fill = NULL
  ) +
  theme( 
    legend.position = "inside",
    legend.position.inside = c(0.10, 0.85),
    legend.background = element_blank()
  ) +
  scale_fill_discrete(
    limits = c("Human", "GPT-5", "Rewritten"),
    breaks = c("Human", "GPT-5")
  )

ggsave(
  path("plots", "appendix", "corr.pdf"),
  p_corr,
  width = 5.3,
  height = 3.3,
  units = "in"
)


## Fig X+1: Receptiveness Transforms Cause Social Syco --------------------

p_share <- rcpt_trans %>%
  mutate(no_syc = !any_syc) %>%
  pivot_longer(
    cols = c(
      validation, indirectness, positivity, any_syc, any_elephant, no_syc,
      framing
    )
  ) %>%
  group_by(name, speaker) %>%
  summarize(
    share = mean(value),
    se = sqrt(share * (1 - share) / n()),
    n = n()
  ) %>%
  ungroup() %>%
  complete(
    name, speaker,
    fill = list(share = 0, se = 0, n = 0)
  ) %>%
  filter(speaker != "GPT-5") %>%
  mutate(
    name = factor(
      name,
      labels = c("None", "Framing", "Indirectness", "Validation",
                 "Any\nELEPHANT", "Sharma\nPositivity", "Any"),
      levels = c("no_syc", "framing", "indirectness", "validation",
                 "any_elephant", "positivity", "any_syc")
    )
  ) %>%
  ggplot(aes(x = name, y = share, fill = speaker)) +
  geom_col(position = "dodge") +
  geom_errorbar(
    aes(ymin = share - 2 * se, ymax = share + 2 * se),
    position = position_dodge(width = 0.9),
    color = "black",
    width = .1
  ) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  labs(
    y = "Share of comments",
    x = "Social Sycophancy Measure",
    fill = NULL
  ) +
  theme(
    legend.position = "inside",
    legend.position.inside = c(.1, .8),
    legend.background = element_blank()
  ) +
  scale_fill_discrete(
    limits = c("Human", "GPT-5", "Rewrite"),
    breaks = c("Human", "Rewrite")
  )

ggsave(
  path("plots", "appendix", "shift.pdf"),
  p_share,
  width = 5.3,
  height = 3.3,
  units = "in"
)

## Qual dist by verdict ----------------------------------------------------

p_quality_dist_verdict <- exp_qual %>%
  count(speaker, verdict_bin, quality = quality_f) %>%
  complete(speaker, quality, verdict_bin, fill = list(n = 0)) %>% 
  group_by(speaker, verdict_bin) %>%
  mutate(share = n / sum(n)) %>%
  ungroup() %>%
  filter(verdict_bin != "Unsure") %>%
  ggplot(aes(x = quality, y = share, fill = speaker)) +
  geom_col(position = position_dodge(width = 0.9), width = 0.85) + 
  facet_wrap(~ verdict_bin) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  scale_x_discrete(drop = FALSE) +
  labs(
    y = "Share of ratings",
    x = "Quality (1 = Very bad, 7 = Very good)",
    fill = NULL
  ) +
  theme(
    legend.position = "inside",
    legend.position.inside = c(0.1, 0.85),
    legend.background = element_blank()
  ) +
  scale_fill_discrete(limits = c("Human", "Rewrite"))

ggsave(
  path("plots", "quality_by_verdict.pdf"),
  p_quality_dist_verdict,
  width = 5.3,
  height = 3.3,
  units = "in"
)

## Pref share by verdict --------------------------------------------

p_listen_verdict <- exp %>%
  count(verdict_bin, score = listen_pref_rewrite) %>%
  filter(verdict_bin != "Unsure") %>% 
  mutate(
    share = n / sum(n),
    se = sqrt(share * (1 - share) / sum(n)),
    score = factor(
      score,
      levels = c(-2, -1, 0, 1, 2),
      labels = c(
        "Definitely\nhuman",
        "Probably\nhuman",
        "Tie",
        "Probably\nrewrite",
        "Definitely\nrewrite"
      )
    )
  ) %>%
  ggplot(aes(x = score, y = share, fill = verdict_bin)) +
  geom_col(width = 0.85, position = position_dodge(width = 0.9)) +
  geom_errorbar(
    aes(ymin = pmax(0, share - 2 * se), ymax = share + 2 * se),
    width = 0.1,
    color = "black",
    position = position_dodge(width = 0.9)
  ) +
  scale_y_continuous(
    labels = scales::percent_format(accuracy = 1),
    limits = c(0, NA)
  ) +
  scale_x_discrete(drop = FALSE) +
  labs(
    y = "Share of ratings",
    x = NULL,
    fill = NULL,
  ) +
  theme(
    plot.title = element_text(size = 10, hjust = 0.5),
    legend.position = "inside",
    legend.position.inside = c(0.2, 0.85),
    legend.background = element_blank()
  )

p_advice_verdict <- exp %>%
  count(verdict_bin, score = advice_pref_rewrite) %>%
  filter(verdict_bin != "Unsure") %>%
  mutate(
    share = n / sum(n),
    se = sqrt(share * (1 - share) / sum(n)),
    score = factor(
      score,
      levels = c(-2, -1, 0, 1, 2),
      labels = c(
        "Definitely\nhuman",
        "Probably\nhuman",
        "Tie",
        "Probably\nrewrite",
        "Definitely\nrewrite"
      )
    )
  ) %>%
  ggplot(aes(x = score, y = share, fill = verdict_bin)) +
  geom_col(width = 0.85, position = position_dodge(width = 0.9)) +
  geom_errorbar(
    aes(ymin = pmax(0, share - 2 * se), ymax = share + 2 * se),
    width = 0.1,
    color = "black",
    position = position_dodge(width = 0.9)
  ) +
  scale_y_continuous(
    labels = scales::percent_format(accuracy = 1),
    limits = c(0, NA)
  ) +
  scale_x_discrete(drop = FALSE) +
  labs(
    y = "Share of ratings",
    x = NULL,
    fill = NULL,
  ) +
  theme(
    plot.title = element_text(size = 10, hjust = 0.5),
    legend.position = "inside",
    legend.position.inside = c(0.2, 0.85),
    legend.background = element_blank()
  )

ggsave(
  path("plots", "advice_personal.pdf"),
  p_advice_verdict,
  width = 3.3,
  height = 3.3,
  units = "in"
)

ggsave(
  path("plots", "advice_listen.pdf"),
  p_listen,
  width = 3.3,
  height = 3.3,
  units = "in"
)

## Does prolific think YTA? ------------------------------------------------

p_verdicts <- exp %>%
  count(verdict_label) %>%
  group_by(verdict_label) %>%
  mutate(verdict_label = factor(
    verdict_label,
    levels = c("Definitely not in the wrong", "Probably not in the wrong",
               "Unsure", "Probably in the wrong",
               "Definitely in the wrong"),
    labels = c("Definitely not\nin the wrong", "Probably not\nin the wrong",
               "Unsure", "Probably in\nthe wrong",
               "Definitely in\nthe wrong")
  )) %>% 
  ungroup() %>%
  mutate(share = n / sum(n)) %>%
  ungroup() %>%
  ggplot(aes(x = verdict_label, y = share)) +
  geom_col() +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  scale_x_discrete(drop = FALSE) +
  labs(
    y = "Share of ratings",
    x = "Prolfic judgements",
    fill = NULL
  ) 

ggsave(
  path("plots", "verdicts_dist.pdf"),
  p_verdicts,
  width = 3.3,
  height = 3.3,
  units = "in"
)

## Quality delta by item, with receptiveness -------------------------------

item_delta <- exp %>%
  group_by(item_id) %>%
  summarize(
    est = mean(quality_rewrite_minus_human),
    se = sd(quality_rewrite_minus_human) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  left_join(exp_items, by = "item_id")

p_delta_bars <- item_delta %>%
  mutate(item_id = fct_reorder(item_id, est)) %>%
  ggplot(aes(x = item_id, y = est, fill = rec_delta)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "grey50") +
  geom_col(width = 0.8) +
  geom_errorbar(
    aes(ymin = est - 2 * se, ymax = est + 2 * se),
    width = 0.2,
    color = "black"
  ) +
  scale_fill_gradient2(
    low = "#b2182b",
    mid = "grey90",
    high = "#2166ac",
    midpoint = median(item_delta$rec_delta)
  ) +
  labs(
    y = "Quality (rewrite - human)",
    x = "Item",
    fill = "Rec. diff."
  ) +
  theme(
    axis.text.x = element_text(angle = 45, hjust = 1, size = 7),
    legend.position = "right"
  )

ggsave(
  path("plots", "advice_deltas_yta.pdf"),
  p_delta_bars,
  width = 5.3,
  height = 3.3,
  units = "in"
)

# Receptiveness delta -----------------------------------------------------

p_delta_scatter <- item_delta %>%
  ggplot(aes(x = rec_z_human, y = rec_z_rewrite)) +
  geom_abline(slope = 1, intercept = 0, linetype = "dashed", color = "grey50") +
  geom_point() +
  labs(
    x = "Human receptiveness",
    y = "Rewrite receptiveness"
  )

p_delta <- plot_grid(
  p_delta_bars,
  p_delta_scatter,
  nrow = 1,
  rel_widths = c(1.35, 1),
  labels = c("A", "B"),
  label_size = 11
)

ggsave(
  path("plots", "advice_delta_by_item.pdf"),
  p_delta,
  width = 7.5,
  height = 3.3,
  units = "in"
)


## Survey Social Syc -------------------------------------------------------
survey_ids <- jsonlite::fromJSON(path("data", "experiment", "items.json"))$id

p_share_survey <- rcpt_trans %>%
  filter(row_idx %in% survey_ids) %>%
  mutate(no_syc = !any_syc) %>%
  pivot_longer(
    cols = c(
      validation, indirectness, positivity, any_syc, any_elephant, no_syc,
      framing
    )
  ) %>%
  filter(value != 0) %>%
  group_by(name, speaker) %>%
  summarize(
    rec_z_est = mean(rec_z),
    se_z = sd(rec_z) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  complete(
    name, speaker,
    fill = list(rec_z_est = NA, se_z = NA, n = 0)
  ) %>%
  filter(speaker != "GPT-5") %>%
  mutate(
    name = factor(
      name,
      labels = c("None", "Framing", "Indirectness", "Validation",
                 "Any\nELEPHANT", "Sharma\nPositivity", "Any"),
      levels = c("no_syc", "framing", "indirectness", "validation",
                 "any_elephant", "positivity", "any_syc")
    )
  ) %>%
  ggplot(aes(x = name, y = rec_z_est, fill = speaker)) +
  geom_col(position = "dodge") +
  scale_fill_discrete(
    limits = c("Human", "GPT-5", "Rewrite"),
    breaks = c("Human", "Rewrite")
  ) +
  labs(
    y = "Receptiveness",
    x = "Social Sycophancy Measure",
    fill = NULL
  ) +
  theme(
    legend.position = "inside",
    legend.position.inside = c(.10, .85),
    legend.background = element_blank()
  )

ggsave(
  path("plots", "shift_survey_n20.pdf"),
  p_share_survey,
  width = 5.3,
  height = 3.3,
  units = "in"
)


