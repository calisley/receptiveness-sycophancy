if (!requireNamespace("groundhog", quietly = TRUE)) {
  install.packages("groundhog", repos = "https://cloud.r-project.org")
}
library(groundhog)

groundhog.library(
  c("fs", "tidyverse", "cowplot", "jsonlite", "patchwork", "politeness"),
  date = "2026-08-22"
)

dir_create(path("plots"))
dir_create(path("plots", "appendix"))

theme_set(
  theme_bw(base_size = 9)
)

# Data --------------------------------------------------------------------

aita_soc_df <- read_csv(
  path("data", "aita_sycophancy_scores.csv")
) %>%
  filter(speaker != "GPT-5") %>%
  group_by(speaker, row_idx) %>%
  # Aggregate average human positivity in comparison to models
  summarize(
    across(
      # framing_v2 is the OLD framing prompt
      c(validation, indirectness, framing, framing_v2, positivity, rec_raw),
      \(x) mean(x, na.rm = TRUE)
    ),
    .groups = "drop"
  ) %>%
  mutate(
    # make it binary so bins stay categorical
    positivity = as.integer(positivity >= 0.5),
    speaker = factor(speaker,
                     levels = c("Human", "GPT-5", "Rewrite", "Gemini 3.7 Flash",
                                "Claude Sonnet 5", "GPT-5.6 Terra",
                                "Llama 4 Scout")
    ),
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"], na.rm = TRUE)) /
      sd(rec_raw[speaker == "Human"], na.rm = TRUE),
    any_elephant = validation | indirectness | framing_v2,
    any_syc = validation | indirectness | framing_v2 | positivity
  )


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

# Fig2 receptive-rewrite panel. Main-text Figure 2 uses the original n = 808
# subset (GPT-5 auxiliary 1p verdict = YTA). The full eligible panel
# (n = 1,892) is kept as rcpt_trans_all for robustness checks at the end.
rcpt_trans_all <- read_csv(
  path("data", "receptiveness_transform.csv")
) %>%
  mutate(
    speaker = factor(speaker, levels = c("Human", "GPT-5", "Rewrite")),
    any_elephant = validation | indirectness | framing_v2,
    any_syc = validation | indirectness | framing_v2 | positivity
  )

fig2_row_idx <- aita_verdicts_1p %>%
  filter(model == "GPT-5", verdict == "YTA") %>%
  semi_join(rcpt_trans_all %>% distinct(row_idx), by = "row_idx") %>%
  pull(row_idx)

rcpt_trans <- rcpt_trans_all %>%
  filter(row_idx %in% fig2_row_idx) %>%
  mutate(
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"])) /
      sd(rec_raw[speaker == "Human"])
  )

judged_v3_all <- read_lines(
  path("data", "receptiveness_transform_judged.jsonl")
) %>%
  keep(~ nzchar(.x)) %>%
  map(fromJSON, simplifyVector = FALSE)

judged_v3 <- judged_v3_all[
  vapply(
    judged_v3_all,
    function(j) as.integer(j$row_idx) %in% fig2_row_idx,
    logical(1)
  )
]

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
    n_words_base = n_words_base,
    n_words_rewrite = n_words_rewrite,
    words_delta = n_words_rewrite - n_words_base,
    rewrite_more_positive = rec_z_rewrite > rec_z_base,
    origin = origin,
    model = model,
    model_label = model_label
  )

front_models <- c(
  "GPT-5.6 Terra", "Claude Sonnet 5", "Gemini 3.7 Flash", "Llama 4 Scout"
)
front_models_mit <- c("Claude Sonnet 5", "Gemini 3.7 Flash")
front_verdicts <- read_csv(path("data", "mitigation", "frontier.csv")) %>%
  select(model, row_idx, verdict_1p)

front_long <- read_csv(path("data", "mitigation", "transform.csv")) %>%
  mutate(
    arm = factor(arm, levels = c("free", "prompt", "tool")),
    landing = na_if(landing, "")
  ) %>%
  left_join(front_verdicts, by = c("model", "row_idx"))

shared_row_idx <- front_long %>%
  filter(arm == "prompt", model %in% front_models_mit) %>%
  distinct(row_idx)

front_T_shared <- front_long %>%
  filter(
    model %in% front_models,
    arm %in% c("free", "tool") |
      (arm == "prompt" & model %in% front_models_mit)
  ) %>%
  semi_join(shared_row_idx, by = "row_idx") %>%
  group_by(model_key, model, arm) %>%
  summarize(
    n = sum(landing %in% c("1p_softer", "3p_softer", "same"), na.rm = TRUE),
    n_1p_softer = sum(landing == "1p_softer", na.rm = TRUE),
    n_3p_softer = sum(landing == "3p_softer", na.rm = TRUE),
    n_tie = sum(landing == "same", na.rm = TRUE),
    T = (n_1p_softer + 0.5 * n_tie) / n,
    n_rec_yta = sum(verdict_1p == "YTA" & !is.na(rec_raw), na.rm = TRUE),
    rec_raw = mean(rec_raw[verdict_1p == "YTA"], na.rm = TRUE),
    rec_se = sd(rec_raw[verdict_1p == "YTA"], na.rm = TRUE) /
      sqrt(sum(verdict_1p == "YTA" & !is.na(rec_raw), na.rm = TRUE)),
    .groups = "drop"
  ) %>%
  mutate(
    se = sqrt(
      (n_1p_softer + n_3p_softer - (n_1p_softer - n_3p_softer)^2 / n) /
        (4 * n^2)
    ),
    lo = T - 1.96 * se,
    hi = T + 1.96 * se
  )


mu_h <- mean(aita_soc_df$rec_raw[aita_soc_df$speaker == "Human"], na.rm = TRUE)
sd_h <- sd(aita_soc_df$rec_raw[aita_soc_df$speaker == "Human"], na.rm = TRUE)

# ELEPHANT OEQ robustness long table 
oeq_df <- read_csv(path("data", "robustness", "oeq", "oeq_long.csv")) %>%
  mutate(
    speaker = factor(speaker, levels = c("Human", "GPT-5")),
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"], na.rm = TRUE)) /
      sd(rec_raw[speaker == "Human"], na.rm = TRUE),
    any_elephant = validation | indirectness | framing_v2,
    any_syc = validation | indirectness | framing_v2 | positivity
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
  filter(speaker != "GPT-5", speaker != "Rewrite") %>%
  mutate(
    total_syc = validation + indirectness + positivity + framing_v2
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
    legend.position.inside = c(0.8, 0.275),
    legend.background = element_blank(),
    legend.key = element_blank()
  ) +
  scale_color_discrete(
    limits = c("Human", "GPT-5", "Rewrite", "Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout"),
    breaks = c("Human","Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout")
  ) +
  guides(
    size = "none"
  )

ggsave(
  path("plots", "corr_cont.pdf"),
  p_corr_cont,
  width = 3.3,
  height = 2.5,
  units = "in"
)

## Fig 2: Shift Continuous (n = 808; GPT-5 auxiliary YTA subset) ---------

p_share_cont <- rcpt_trans %>%
  mutate(
    total_syc = validation + indirectness + positivity + framing_v2
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
  height = 2.5,
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
    legend.position.inside = c(0.875, 0.325),
    legend.background = element_rect(
      color = "black",
      linewidth = 0.5,
      fill = NA
    ),
    legend.key.size = unit(0.8, "lines"),
    legend.key.spacing.y = unit(1, "pt"),
    legend.text = element_text(margin = margin(l = 1)),
    legend.margin = margin(2, 2, 2, 2),
    legend.box.margin = margin(0, 0, 0, 0),
    legend.key = element_blank(),
    strip.background = element_blank(),
    strip.text = element_text(size = 9, margin = margin(t = 1, b = 1)),
  )

ggsave(
  path("plots", "pref_vs_rec.pdf"),
  p_pref_vs_rec,
  width = 3.3,
  height = 2.5,
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
  width = 6.6, height = 2.5, units = "in"
)

## Fig 5: Substantive Syc ---------------------------------------------------------

df_front <- front_T_shared %>%
  filter(arm %in% c("free", "tool"), model %in% front_models) %>%
  select(model_key, model, arm, T, rec_raw, n, n_rec_yta) %>%
  pivot_wider(
    names_from = arm,
    values_from = c(T, rec_raw, n, n_rec_yta),
    names_glue = "{.value}_{arm}"
  ) %>%
  transmute(
    model,
    n = n_free,
    n_rec_yta = n_rec_yta_free,
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

stopifnot(all(df_front$n == 200))

p_front <- ggplot(df_front, aes(color = model, fill = model, shape = model)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "grey40") +
  geom_vline(xintercept = 0.5, linetype = "dashed", color = "grey40") +
  geom_segment(
    data = df_front %>% filter(model %in% front_models_mit),
    aes(x = T_start, y = rec_z_start, xend = T_end, yend = rec_z_end),
    arrow = arrow(length = unit(0.07, "in"), type = "closed"),
    linewidth = 0.45,
    show.legend = FALSE
  ) +
  geom_point(aes(x = T_free, y = rec_z_free), size = 2.8, stroke = 0.6) +
  geom_point(
    data = df_front %>% filter(model %in% front_models_mit),
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
    y = "Receptiveness | 1p == In the wrong",
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
  height = 2.5,
  units = "in"
)

# Main text statistics ----------------------------------------------------

## Receptiveness measure, validation against the package -------------------

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

message("\n=== Main text: HEAR rubric CV correlation with human scores ===")
hear_train %>%
  summarize(
    r_rubric_cv = cor(pred_cv, receptive_human),
    n = n()
  )

tryCatch(
  {
    message("\n=== Main text: politeness package correlation (in-sample) ===")
    hear_train %>%
      mutate(pred_package = politeness::receptiveness(text)) %>%
      summarize(r_package = cor(pred_package, receptive_human))
  },
  error = function(e) {
    message(
      "Skipping politeness::receptiveness() (spaCy not installed). ",
      "Optional one-time fix in R: spacyr::spacy_install(); then rerun."
    )
    invisible(NULL)
  }
)


## Figure 1: receptiveness vs social sycophancy (AITA-YTA) -----------------

message("\n=== Main text: pooled r(total social sycophancy, receptiveness), AITA-YTA ===")
aita_soc_df %>%
  filter(speaker != "Rewrite") %>%
  mutate(total_syc = validation + indirectness + positivity + framing_v2) %>%
  summarize(
    r_pooled = cor(total_syc, rec_z, use = "complete.obs"),
    n = n()
  )


## Cross-domain: OEQ -------------------------------------------------------

message("\n=== Main text: pooled r(total social sycophancy, receptiveness), OEQ ===")
oeq_df %>%
  mutate(total_syc = validation + indirectness + positivity + framing_v2) %>%
  summarize(
    r_pooled = cor(total_syc, rec_z, use = "complete.obs"),
    n = n()
  )


## Receptiveness rewrite (n = 808) --------------------------------

message("\n=== Main text: receptiveness gain from listen_once rewrite (n=808) ===")
rcpt_trans %>%
  select(row_idx, speaker, rec_z) %>%
  pivot_wider(names_from = speaker, values_from = rec_z) %>%
  mutate(delta = Rewrite - Human) %>%
  summarize(
    est = mean(delta),
    se = sd(delta) / sqrt(n()),
    n = n()
  ) %>%
  mutate(lo = est - 1.96 * se, hi = est + 1.96 * se)

message("\n=== Main text: verdict preservation rate (substance judge, n=808) ===")
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


## Human experiment design -------------------------------------------------

message("\n=== Main text: mean receptiveness gain on survey items, by origin ===")
exp_items %>%
  group_by(origin) %>%
  summarize(
    est = mean(rec_delta),
    se = sd(rec_delta) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(lo = est - 1.96 * se, hi = est + 1.96 * se)

message("\n=== Main text: mean rewrite length change (words), by origin ===")
exp_items %>%
  group_by(origin) %>%
  summarize(
    mean_words_delta = mean(words_delta),
    se = sd(words_delta) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(
    lo = mean_words_delta - 1.96 * se,
    hi = mean_words_delta + 1.96 * se
  )


## Experimental results / length Controls -----------------------------------------------

exp_part <- read_csv(path("data", "experiment", "participants.csv"))

MANUAL_PARAPHRASE_FAIL <- "6a0c93436c009b0e6c8a3fda"

prereg_exclude_pids <- exp_part %>%
  filter(
    is.na(outro_paraphrase) |
      trimws(outro_paraphrase) == "" |
      nchar(trimws(outro_paraphrase)) < 10L |
      prolific_pid == MANUAL_PARAPHRASE_FAIL
  ) %>%
  pull(prolific_pid)

exp_prereg <- exp %>%
  filter(!prolific_pid %in% prereg_exclude_pids)

exp_len <- exp %>%
  left_join(exp_items %>% select(item_id, words_delta), by = "item_id")

exp_len_prereg <- exp_prereg %>%
  left_join(exp_items %>% select(item_id, words_delta), by = "item_id")

fmt_ci_latex <- function(est, lo, hi) {
  lo_str <- sprintf("%.2f", lo)
  hi_str <- sprintf("%.2f", hi)
  if (startsWith(lo_str, "-")) lo_str <- paste0("$", lo_str, "$")
  if (startsWith(hi_str, "-")) hi_str <- paste0("$", hi_str, "$")
  paste0(sprintf("%.2f", est), " [", lo_str, ", ", hi_str, "]")
}

mean_ci_by_prov <- function(df, outcome_var, yta_only = FALSE) {
  if (yta_only) {
    df <- dplyr::filter(df, verdict_bin == "In the wrong")
  }
  df %>%
    dplyr::group_by(provenance) %>%
    dplyr::summarize(
      est = mean(.data[[outcome_var]], na.rm = TRUE),
      se = sd(.data[[outcome_var]], na.rm = TRUE) / sqrt(n()),
      n = dplyr::n(),
      .groups = "drop"
    ) %>%
    dplyr::mutate(
      lo = est - 1.96 * se,
      hi = est + 1.96 * se
    )
}

length_int_by_prov <- function(df, outcome_var, yta_only = FALSE) {
  if (yta_only) {
    df <- dplyr::filter(df, verdict_bin == "In the wrong")
  }
  df %>%
    dplyr::group_by(provenance) %>%
    dplyr::group_modify(\(d, ...) {
      fit <- lm(
        as.formula(paste0(outcome_var, " ~ words_delta")),
        data = d
      )
      co <- summary(fit)$coefficients
      tibble(
        est = unname(co[1, 1]),
        se = unname(co[1, 2]),
        n = nrow(d)
      )
    }) %>%
    ungroup() %>%
    dplyr::mutate(
      lo = est - 1.96 * se,
      hi = est + 1.96 * se
    )
}

robustness_row_specs <- tribble(
  ~outcome_var, ~provenance, ~yta_only, ~latex_label, ~addlinespace_after,
  "quality_rewrite_minus_human", "Human", FALSE,
  "Quality $\\Delta$ (human-origin)", FALSE,
  "quality_rewrite_minus_human", "Model", FALSE,
  "Quality $\\Delta$ (model-origin)", TRUE,
  "quality_rewrite_minus_human", "Human", TRUE,
  "Quality $\\Delta$, YTA only (human-origin)", FALSE,
  "quality_rewrite_minus_human", "Model", TRUE,
  "Quality $\\Delta$, YTA only (model-origin)", TRUE,
  "listen_pref_rewrite", "Human", FALSE,
  "Listen preference (human-origin)", FALSE,
  "listen_pref_rewrite", "Model", FALSE,
  "Listen preference (model-origin)", TRUE,
  "listen_pref_rewrite", "Human", TRUE,
  "Listen preference, YTA only (human-origin)", FALSE,
  "listen_pref_rewrite", "Model", TRUE,
  "Listen preference, YTA only (model-origin)", TRUE,
  "advice_pref_rewrite", "Human", FALSE,
  "Advice preference (human-origin)", FALSE,
  "advice_pref_rewrite", "Model", FALSE,
  "Advice preference (model-origin)", TRUE,
  "advice_pref_rewrite", "Human", TRUE,
  "Advice preference, YTA only (human-origin)", FALSE,
  "advice_pref_rewrite", "Model", TRUE,
  "Advice preference, YTA only (model-origin)", FALSE
)

exp_robustness_table <- purrr::pmap_dfr(
  robustness_row_specs,
  \(outcome_var, provenance, yta_only, latex_label, addlinespace_after) {
    n200 <- mean_ci_by_prov(exp, outcome_var, yta_only) %>%
      dplyr::filter(provenance == !!provenance)
    n196 <- mean_ci_by_prov(exp_prereg, outcome_var, yta_only) %>%
      dplyr::filter(provenance == !!provenance)
    len200 <- length_int_by_prov(exp_len, outcome_var, yta_only) %>%
      dplyr::filter(provenance == !!provenance)
    len196 <- length_int_by_prov(exp_len_prereg, outcome_var, yta_only) %>%
      dplyr::filter(provenance == !!provenance)
    tibble(
      latex_label = latex_label,
      addlinespace_after = addlinespace_after,
      n200 = fmt_ci_latex(n200$est, n200$lo, n200$hi),
      n196 = fmt_ci_latex(n196$est, n196$lo, n196$hi),
      length200 = fmt_ci_latex(len200$est, len200$lo, len200$hi),
      length196 = fmt_ci_latex(len196$est, len196$lo, len196$hi)
    )
  }
)

dir_create(path("tables"))

exp_robustness_csv <- exp_robustness_table %>%
  dplyr::transmute(
    Outcome = latex_label,
    `Main text (n=200)` = n200,
    `Prereg exclusion (n=196)` = n196,
    `Length-controlled (n=200)` = length200,
    `Length-controlled (n=196)` = length196
  )

readr::write_csv(
  exp_robustness_csv,
  path("tables", "exp_human_robustness.csv")
)

row_lines <- purrr::pmap_chr(
  exp_robustness_table,
  \(latex_label, n200, n196, length200, length196, addlinespace_after) {
    line <- paste0(
      latex_label,
      "\n    & ", n200,
      "\n    & ", n196,
      "\n    & ", length200,
      "\n    & ", length196,
      " \\\\"
    )
    if (isTRUE(addlinespace_after)) {
      paste0(line, "\n\\addlinespace")
    } else {
      line
    }
  }
)

writeLines(
  c(
    "\\begin{table*}[t]",
    "\\centering",
    "\\small",
    "\\caption{Human-study robustness and length-controlled estimates. Point estimates",
    "are reported with 95\\% confidence intervals in brackets.}",
    "\\label{tab:length_controls}",
    "\\begin{tabular}{@{}lcccc@{}}",
    "\\toprule",
    "& Main text",
    "& Preregistered exclusions",
    "& \\multicolumn{2}{c}{Length controlled} \\\\",
    "& ($n=200$)",
    "& ($n=196$)",
    "& ($n=200$)",
    "& ($n=196$) \\\\",
    "\\midrule",
    row_lines,
    "\\bottomrule",
    "\\multicolumn{5}{@{}p{0.96\\textwidth}@{}}{\\footnotesize",
    "\\textit{Note.} The preregistered-exclusion specification removes four",
    "participants who failed the end-of-survey response-quality check. The",
    "length-controlled estimates are intercepts from",
    "$\\Delta Y = \\alpha + \\beta\\,\\Delta\\mathrm{Words} + \\epsilon$, estimated on the",
    "full sample ($n=200$) and on the preregistered-exclusion sample ($n=196$).}",
    "\\end{tabular}",
    "\\end{table*}"
  ),
  path("tables", "exp_human_robustness.tex")
)

message(
  "Wrote tables/exp_human_robustness.{csv,tex} (prereg paraphrase exclusions: ",
  length(prereg_exclude_pids), " participants)."
)

message("\n=== human experiment outcomes (raw, n=200) ===")
print(exp_robustness_csv %>% select(Outcome, `Main text (n=200)`))

## Figure 3: preference vs baseline receptiveness --------------------------

message("\n=== Main text: preference gap slope vs original receptiveness (item-level) ===")
exp %>%
  group_by(item_id, provenance, rec_z_base) %>%
  summarize(
    listen = mean(listen_pref_rewrite),
    advice = mean(advice_pref_rewrite),
    .groups = "drop"
  ) %>%
  pivot_longer(cols = c(listen, advice), names_to = "item", values_to = "pref") %>%
  group_by(item) %>%
  summarize(
    slope = coef(lm(pref ~ rec_z_base))[2],
    se = summary(lm(pref ~ rec_z_base))$coefficients[2, 2],
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(lo = slope - 1.96 * se, hi = slope + 1.96 * se)


message("\n=== Main text: share judging asker in the wrong (verdict >= 4) ===")
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

message("\n== Main text: share judging asker not in the wrong (verdict <= 2) =")
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

## Mitigation ----------------------------------------------------

message("\n=== Main text: mitigation free baseline (n=200, all models) ===")
front_T_shared %>%
  filter(arm == "free") %>%
  select(model, T, se, lo, hi, rec_raw, rec_se, n_rec_yta, n)

message("\n=== Main text: mitigation free vs prompt (Sonnet / Flash) ===")
front_T_shared %>%
  filter(model %in% front_models_mit, arm %in% c("free", "prompt")) %>%
  select(model_key, model, arm, T, se, lo, hi, rec_raw, rec_se, n_rec_yta, n) %>%
  pivot_wider(
    names_from = arm,
    values_from = c(T, se, lo, hi, rec_raw, rec_se, n_rec_yta, n),
    names_glue = "{.value}_{arm}"
  ) %>%
  transmute(
    model,
    n = n_prompt,
    T_free,
    se_T_free = se_free,
    lo_T_free = lo_free,
    hi_T_free = hi_free,
    T_prompt,
    se_T_prompt = se_prompt,
    lo_T_prompt = lo_prompt,
    hi_T_prompt = hi_prompt,
    n_rec_yta_free,
    rec_z_free = (rec_raw_free - mu_h) / sd_h,
    se_rec_z_free = rec_se_free / sd_h,
    lo_rec_z_free = rec_z_free - 1.96 * se_rec_z_free,
    hi_rec_z_free = rec_z_free + 1.96 * se_rec_z_free,
    rec_z_prompt = (rec_raw_prompt - mu_h) / sd_h,
    se_rec_z_prompt = rec_se_prompt / sd_h,
    lo_rec_z_prompt = rec_z_prompt - 1.96 * se_rec_z_prompt,
    hi_rec_z_prompt = rec_z_prompt + 1.96 * se_rec_z_prompt,
    dz_prompt = rec_z_prompt - rec_z_free,
    se_dz_prompt = sqrt(se_rec_z_free^2 + se_rec_z_prompt^2),
    lo_dz_prompt = dz_prompt - 1.96 * se_dz_prompt,
    hi_dz_prompt = dz_prompt + 1.96 * se_dz_prompt
  )

message("\n=== Main text: mitigation free vs tool (Sonnet / Flash) ===")
front_T_shared %>%
  filter(model %in% front_models_mit, arm %in% c("free", "tool")) %>%
  select(model_key, model, arm, T, se, lo, hi, rec_raw, rec_se, n_rec_yta, n) %>%
  pivot_wider(
    names_from = arm,
    values_from = c(T, se, lo, hi, rec_raw, rec_se, n_rec_yta, n),
    names_glue = "{.value}_{arm}"
  ) %>%
  transmute(
    model,
    n = n_free,
    T_free,
    se_T_free = se_free,
    lo_T_free = lo_free,
    hi_T_free = hi_free,
    T_tool,
    se_T_tool = se_tool,
    lo_T_tool = lo_tool,
    hi_T_tool = hi_tool,
    n_rec_yta_free,
    rec_z_free = (rec_raw_free - mu_h) / sd_h,
    se_rec_z_free = rec_se_free / sd_h,
    lo_rec_z_free = rec_z_free - 1.96 * se_rec_z_free,
    hi_rec_z_free = rec_z_free + 1.96 * se_rec_z_free,
    rec_z_tool = (rec_raw_tool - mu_h) / sd_h,
    se_rec_z_tool = rec_se_tool / sd_h,
    lo_rec_z_tool = rec_z_tool - 1.96 * se_rec_z_tool,
    hi_rec_z_tool = rec_z_tool + 1.96 * se_rec_z_tool,
    dz_tool = rec_z_tool - rec_z_free,
    se_dz_tool = sqrt(se_rec_z_free^2 + se_rec_z_tool^2),
    lo_dz_tool = dz_tool - 1.96 * se_dz_tool,
    hi_dz_tool = dz_tool + 1.96 * se_dz_tool
  )

# Appendix ----------------------------------------------------------------

## OEQ correlation (supplement) --------------------------------------------

p_oeq <- oeq_df %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  group_by(speaker, total_syc) %>%
  summarize(
    rec_z_est = mean(rec_z),
    n = n(),
    .groups = "drop"
  ) %>% 
  ungroup() %>% 
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
    legend.position.inside = c(0.8, 0.275),
    legend.background = element_blank(),
    legend.key = element_blank()
  ) +
  scale_color_discrete(
    limits = c("Human", "GPT-5", "Rewrite", "Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout"),
    breaks = c("Human","GPT-5")
  ) +
  guides(
    size = "none"
  )

ggsave(
  path("plots", "appendix", "corr_cont_oeq.pdf"),
  p_oeq,
  width = 3.3,
  height = 3.3,
  units = "in"
)


---------------------------------------------------------------

## Quality distributions ----------------------------------------

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
  path("plots", "appendix", "advice_quality_dist.pdf"),
  p_quality_dist,
  width = 6.6,
  height = 3.3,
  units = "in"
)


## Quality scatter ---------------------------------------------------------

p_quality_scatter <- exp %>%
  group_by(item_id, provenance) %>%
  summarize(
    quality_human = mean(quality_human),
    quality_rewrite = mean(quality_rewrite)
  ) %>%
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
  path("plots", "appendix", "advice_quality_scatter.pdf"),
  p_quality_scatter,
  width = 6.6,
  height = 3.3,
  units = "in"
)


## Social Sycophancy Moves with Receptiveness HIST --------------------

p_corr_hist <- aita_soc_df %>%
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
  filter(speaker != "GPT-5", speaker != "Rewrite") %>%
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
    legend.position.inside = c(0.7, 0.15),
    legend.background = element_blank(),
    
  ) +
  scale_fill_discrete(
    limits = c("Human", "GPT-5", "Rewrite", "Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout"),
    breaks = c("Human","Gemini 3.7 Flash",
               "Claude Sonnet 5", "GPT-5.6 Terra", "Llama 4 Scout")
  ) +
  scale_y_continuous(limits = c(-1, 3)) +
  guides(fill = guide_legend(nrow = 2))

ggsave(
  path("plots", "appendix", "corr_hist.pdf"),
  p_corr_hist,
  width = 6.6,
  height = 3.3,
  units = "in"
)


## Receptiveness Transforms Cause Social Syco --------------------

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
  width = 6.6,
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
  geom_col(position = "dodge") +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  scale_x_discrete(drop = FALSE) +
  labs(
    y = "Share of ratings",
    x = "Prolfic judgements",
    fill = NULL
  ) +
  theme(
    legend.position ="inside",
    legend.position.inside = c(.2, .8),
    legend.background = element_blank(),
    legend.key = element_blank(),
    axis.text.x = element_text(size = 9, angle = 45, hjust = 1)
  )

ggsave(
  path("plots", "appendix", "verdicts_dist.pdf"),
  p_verdicts,
  width = 3.3,
  height = 3.3,
  units = "in"
)

# Appendix statistics -----------------------------------------------------

## Raw 1p verdict rates (YTA / NTA / mixed / other) ------------------------

N_aita <- 2000L

dens_by_model <- aita_soc_df %>%
  filter(speaker != "Human", speaker != "Rewrite") %>%
  count(model = speaker, name = "dens_clear_yta")

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
  left_join(dens_by_model, by = "model") %>%
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
    dens_clear_yta,
    dens_over_2000 = dens_clear_yta / N_aita
  )

message("\n=== Supplement: raw Luna 1p verdict rates by model (N=2000) ===")
aita_verdict_rates_wide


message("\n=== Supplement: share judging asker not in the wrong (verdict <= 2) ===")
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


## Robustness checks -------------------------------------------------------

# Supplement: expanded fig2 panel (n = 1,892) and framing-prompt sensitivity
# (contaminated framing_v2 vs corrected framing vs omit framing).

rcpt_trans_expanded <- rcpt_trans_all %>%
  mutate(
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"])) /
      sd(rec_raw[speaker == "Human"])
  )

## Expanded fig2 panel (n = 1,892) -----------------------------------------

# Receptiveness gain on the full eligible human-comment panel.
message("\n=== Supplement: receptiveness gain, expanded fig2 panel (n=1,892) ===")
rcpt_trans_expanded %>%
  select(row_idx, speaker, rec_z) %>%
  pivot_wider(names_from = speaker, values_from = rec_z) %>%
  mutate(delta = Rewrite - Human) %>%
  summarize(
    panel = "fig2_expanded",
    est = mean(delta),
    se = sd(delta) / sqrt(n()),
    n = n(),
    .groups = "drop"
  ) %>%
  mutate(lo = est - 1.96 * se, hi = est + 1.96 * se)

# Verdict preservation on the expanded panel.
message("\n=== Supplement: verdict preservation, expanded fig2 panel (n=1,892) ===")
{
  n <- length(judged_v3_all)
  k <- sum(vapply(
    judged_v3_all,
    function(j) as.integer(j$verdict_same),
    integer(1)
  ))
  bt <- binom.test(k, n, conf.level = 0.95)
  tibble(
    panel = "fig2_expanded",
    k = k,
    n = n,
    est = as.numeric(bt$estimate),
    lo = bt$conf.int[1],
    hi = bt$conf.int[2]
  )
}

## Framing-prompt sensitivity ----------------------------------------------

# AITA-YTA (collapsed aita_soc_df; same estimand as Figure 1 correlation).
message("\n=== Supplement: framing-prompt sensitivity, AITA-YTA correlations ===")
aita_soc_df %>%
  filter(speaker != "Rewrite") %>%
  mutate(
    total_syc_v3 = validation + indirectness + positivity + framing,
    total_syc_v2 = validation + indirectness + positivity + framing_v2,
    total_syc_nof = validation + indirectness + positivity
  ) %>%
  summarize(
    corpus = "aita_yta",
    n = n(),
    r_v3 = cor(total_syc_v3, rec_z, use = "complete.obs"),
    r_v2 = cor(total_syc_v2, rec_z, use = "complete.obs"),
    r_nof = cor(total_syc_nof, rec_z, use = "complete.obs")
  )

# OEQ cross-domain panel.
message("\n=== Supplement: framing-prompt sensitivity, OEQ correlations ===")
oeq_df %>%
  mutate(
    total_syc_v3 = validation + indirectness + positivity + framing,
    total_syc_v2 = validation + indirectness + positivity + framing_v2,
    total_syc_nof = validation + indirectness + positivity
  ) %>%
  summarize(
    corpus = "oeq",
    n = n(),
    r_v3 = cor(total_syc_v3, rec_z, use = "complete.obs"),
    r_v2 = cor(total_syc_v2, rec_z, use = "complete.obs"),
    r_nof = cor(total_syc_nof, rec_z, use = "complete.obs")
  )

# Paired rewrite Δ total social sycophancy (human → rewrite), by framing spec.
message("\n=== Supplement: rewrite Δ total sycophancy by framing spec (fig2 main) ===")
bind_rows(
  tibble(framing_col = "framing", panel = "fig2_main"),
  tibble(framing_col = "framing_v2", panel = "fig2_main"),
  tibble(framing_col = "omit", panel = "fig2_main")
) %>%
  pmap_dfr(function(framing_col, panel) {
    rcpt_trans %>%
      select(row_idx, speaker, validation, indirectness, positivity, framing,
             framing_v2) %>%
      mutate(
        total_syc = if (framing_col == "omit") {
          validation + indirectness + positivity
        } else if (framing_col == "framing") {
          validation + indirectness + positivity + framing
        } else {
          validation + indirectness + positivity + framing_v2
        }
      ) %>%
      select(row_idx, speaker, total_syc) %>%
      pivot_wider(names_from = speaker, values_from = total_syc) %>%
      mutate(delta = Rewrite - Human) %>%
      summarize(
        panel = panel,
        framing = framing_col,
        est = mean(delta),
        se = sd(delta) / sqrt(n()),
        n = n(),
        .groups = "drop"
      )
  })

# Same rewrite Δ syc on the expanded n = 1,892 panel.
message("\n=== Supplement: rewrite Δ total sycophancy by framing spec (fig2 expanded) ===")
bind_rows(
  tibble(framing_col = "framing", panel = "fig2_expanded"),
  tibble(framing_col = "framing_v2", panel = "fig2_expanded"),
  tibble(framing_col = "omit", panel = "fig2_expanded")
) %>%
  pmap_dfr(function(framing_col, panel) {
    rcpt_trans_expanded %>%
      select(row_idx, speaker, validation, indirectness, positivity, framing,
             framing_v2) %>%
      mutate(
        total_syc = if (framing_col == "omit") {
          validation + indirectness + positivity
        } else if (framing_col == "framing") {
          validation + indirectness + positivity + framing
        } else {
          validation + indirectness + positivity + framing_v2
        }
      ) %>%
      select(row_idx, speaker, total_syc) %>%
      pivot_wider(names_from = speaker, values_from = total_syc) %>%
      mutate(delta = Rewrite - Human) %>%
      summarize(
        panel = panel,
        framing = framing_col,
        est = mean(delta),
        se = sd(delta) / sqrt(n()),
        n = n(),
        .groups = "drop"
      )
  })


message("\n=== Main text: experiment sample sizes ===")
exp %>%
  summarize(
    n_ratings = n(),
    n_participants = n_distinct(prolific_pid),
    n_items = n_distinct(item_id)
  )
