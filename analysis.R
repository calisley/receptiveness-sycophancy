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
      c(validation, indirectness, framing, positivity, rec_raw),
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
    any_elephant = validation | indirectness | framing,
    any_syc = validation | indirectness | framing | positivity
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

# Fig 2 receptive-rewrite panels (receptiveness_transform.csv).
# Expanded (n = 1,892): every distinct row_idx with complete Human + Rewrite
# rows — i.e. AITA human top comment, successful listen-once rewrite, and
# non-missing ELEPHANT + HEAR + positivity scores (see scripts/compile/compile_fig2.py).

rcpt_trans <- read_csv(
  path("data", "receptiveness_transform.csv")
) %>%
  mutate(
    speaker = factor(speaker, levels = c("Human", "GPT-5", "Rewrite")),
    any_elephant = validation | indirectness | framing,
    any_syc = validation | indirectness | framing | positivity,
    rec_z = (rec_raw - mean(rec_raw[speaker == "Human"], na.rm = TRUE)) /
      sd(rec_raw[speaker == "Human"], na.rm = TRUE),
  )

judged_v3_all <- read_lines(
  path("data", "receptiveness_transform_judged.jsonl")
) %>%
  keep(~ nzchar(.x)) %>%
  map(fromJSON, simplifyVector = FALSE)

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

# Full sample of human comments only scored for the receptive transform
mu_h <- mean(rcpt_trans$rec_raw[rcpt_trans$speaker == "Human"], na.rm = TRUE)
sd_h <- sd(rcpt_trans$rec_raw[rcpt_trans$speaker == "Human"], na.rm = TRUE)

# ELEPHANT OEQ robustness long table 
oeq_df <- read_csv(path("data", "robustness", "oeq", "oeq_long.csv")) %>%
  mutate(
    speaker = factor(speaker, levels = c("Human", "GPT-5")),
    rec_z = (rec_raw - mu_h) / sd_h,
    any_elephant = validation | indirectness | framing,
    any_syc = validation | indirectness | framing | positivity
  )

aita_soc_df <- aita_soc_df %>%
  mutate(
    rec_z = (rec_raw - mu_h) / sd_h,
  )

## Experiment --------------------------------------------------------------

exp_qual <- exp %>%
  select(
    response_id,
    participant_id,
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

## Fig 2: Shift Continuous ---------

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
hear_coefs <- double(5)
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
  hear_coefs[k] <- list(fit$coefficients)
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


## Receptiveness vs social sycophancy (AITA-YTA) -----------------

message("\n=== Main text: pooled r(total social sycophancy, receptiveness), AITA-YTA ===")
aita_soc_df %>%
  filter(speaker != "Rewrite") %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  summarize(
    r_pooled = cor(total_syc, rec_z, use = "complete.obs"),
    n = n()
  )

## Cross-domain: OEQ -------------------------------------------------------

message("\n=== Main text: pooled r(total social sycophancy, receptiveness), OEQ ===")
oeq_df %>%
  mutate(total_syc = validation + indirectness + positivity + framing) %>%
  summarize(
    r_pooled = cor(total_syc, rec_z, use = "complete.obs"),
    n = n()
  )

## Receptiveness rewrite  --------------------------------

message("\n=== Main text: receptiveness gain from listen_once rewrite ===")
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

message("\n=== Main text: verdict preservation rate (substance judge, n=1892) ===")
{
  n <- length(judged_v3_all)
  k <- sum(vapply(
    judged_v3_all,
    function(j) as.integer(j$verdict_same),
    integer(1)
  ))
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


## Experimental results / length controls ------------------------------------

exp_part <- read_csv(path("data", "experiment", "participants.csv"))

# Preregistered paraphrase QC exclusions.
prereg_exclude_ids <- exp_part %>%
  filter(
    is.na(outro_paraphrase) |
      trimws(outro_paraphrase) == "" |
      nchar(trimws(outro_paraphrase)) < 10L |
      flag_manual_paraphrase_fail == 1L
  ) %>%
  pull(participant_id)

# Analysis sample with preregistered exclusions and item-level length change.
exp_prereg <- exp %>%
  filter(!participant_id %in% prereg_exclude_ids) %>%
  left_join(
    exp_items %>% select(item_id, words_delta),
    by = "item_id"
  )

# Stack the full preregistered sample and the YTA-only subset so that the
# same code can estimate both.
exp_analysis <- bind_rows(
  exp_prereg %>%
    mutate(sample = "All"),
  exp_prereg %>%
    filter(verdict_bin == "In the wrong") %>%
    mutate(sample = "YTA only")
) %>%
  pivot_longer(
    cols = c(
      quality_rewrite_minus_human,
      listen_pref_rewrite,
      advice_pref_rewrite
    ),
    names_to = "outcome",
    values_to = "value"
  )

# Raw preregistered-sample estimates.
raw_estimates <- exp_analysis %>%
  group_by(outcome, provenance, sample) %>%
  summarise(
    est = mean(value, na.rm = TRUE),
    se = sd(value, na.rm = TRUE) / sqrt(sum(!is.na(value))),
    .groups = "drop"
  ) %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se,
    specification = "Raw Estimates"
  )

# Length-controlled estimates: intercept when words_delta = 0.
length_estimates <- exp_analysis %>%
  filter(!is.na(value), !is.na(words_delta)) %>%
  group_by(outcome, provenance, sample) %>%
  group_modify(\(d, ...) {
    fit <- lm(value ~ words_delta, data = d)
    
    tibble(
      est = unname(coef(fit)[["(Intercept)"]]),
      se = unname(
        summary(fit)$coefficients["(Intercept)", "Std. Error"]
      )
    )
  }) %>%
  ungroup() %>%
  mutate(
    lo = est - 1.96 * se,
    hi = est + 1.96 * se,
    specification = "Length Controlled"
  )

# Combine estimates and make display labels.
exp_robustness_table <- bind_rows(
  raw_estimates,
  length_estimates
) %>%
  mutate(
    latex_label = case_when(
      outcome == "quality_rewrite_minus_human" &
        sample == "All" ~
        "Quality $\\Delta$",
      
      outcome == "quality_rewrite_minus_human" &
        sample == "YTA only" ~
        "Quality $\\Delta$, YTA only",
      
      outcome == "listen_pref_rewrite" &
        sample == "All" ~
        "Listen preference",
      
      outcome == "listen_pref_rewrite" &
        sample == "YTA only" ~
        "Listen preference, YTA only",
      
      outcome == "advice_pref_rewrite" &
        sample == "All" ~
        "Advice preference",
      
      outcome == "advice_pref_rewrite" &
        sample == "YTA only" ~
        "Advice preference, YTA only"
    ),
    latex_label = paste0(
      latex_label,
      " (",
      tolower(provenance),
      "-origin)"
    ),
    
    # Use math mode for negative CI endpoints in LaTeX.
    lo_text = if_else(
      lo < 0,
      paste0("$", sprintf("%.2f", lo), "$"),
      sprintf("%.2f", lo)
    ),
    hi_text = if_else(
      hi < 0,
      paste0("$", sprintf("%.2f", hi), "$"),
      sprintf("%.2f", hi)
    ),
    estimate_ci = paste0(
      sprintf("%.2f", est),
      " [", lo_text, ", ", hi_text, "]"
    ),
    
    # Explicit row order for the table.
    row_order = case_when(
      outcome == "quality_rewrite_minus_human" &
        sample == "All" &
        provenance == "Human" ~ 1L,
      outcome == "quality_rewrite_minus_human" &
        sample == "All" &
        provenance == "Model" ~ 2L,
      outcome == "quality_rewrite_minus_human" &
        sample == "YTA only" &
        provenance == "Human" ~ 3L,
      outcome == "quality_rewrite_minus_human" &
        sample == "YTA only" &
        provenance == "Model" ~ 4L,
      
      outcome == "listen_pref_rewrite" &
        sample == "All" &
        provenance == "Human" ~ 5L,
      outcome == "listen_pref_rewrite" &
        sample == "All" &
        provenance == "Model" ~ 6L,
      outcome == "listen_pref_rewrite" &
        sample == "YTA only" &
        provenance == "Human" ~ 7L,
      outcome == "listen_pref_rewrite" &
        sample == "YTA only" &
        provenance == "Model" ~ 8L,
      
      outcome == "advice_pref_rewrite" &
        sample == "All" &
        provenance == "Human" ~ 9L,
      outcome == "advice_pref_rewrite" &
        sample == "All" &
        provenance == "Model" ~ 10L,
      outcome == "advice_pref_rewrite" &
        sample == "YTA only" &
        provenance == "Human" ~ 11L,
      outcome == "advice_pref_rewrite" &
        sample == "YTA only" &
        provenance == "Model" ~ 12L
    )
  ) %>%
  select(row_order, latex_label, specification, estimate_ci) %>%
  pivot_wider(
    names_from = specification,
    values_from = estimate_ci
  ) %>%
  arrange(row_order)

dir_create(path("tables"))

# CSV ------------------------------------------------------------------------

exp_robustness_csv <- exp_robustness_table %>%
  transmute(
    Outcome = latex_label,
    `Raw Estimates` = `Raw Estimates`,
    `Length-controlled` = `Length Controlled`
  )

write_csv(
  exp_robustness_csv,
  path("tables", "exp_human_robustness.csv")
)

# LaTeX ----------------------------------------------------------------------

exp_robustness_table <- exp_robustness_table %>%
  mutate(
    latex_row = paste0(
      latex_label,
      "\n    & ", `Raw Estimates`,
      "\n    & ", `Length Controlled`,
      " \\\\"
    ),
    latex_row = if_else(
      row_order %in% c(2L, 4L, 6L, 8L, 10L),
      paste0(latex_row, "\n\\addlinespace"),
      latex_row
    )
  )

writeLines(
  c(
    "\\begin{table*}[p]",
    "\\centering",
    "\\small",
    "\\begin{tabularx}{0.98\\textwidth}{@{}Xcc@{}}",
    "\\toprule",
    "& Raw Estimates",
    "& Length Controlled \\\\",
    "\\midrule",
    exp_robustness_table$latex_row,
    "\\bottomrule",
    "",
    "\\multicolumn{3}{@{}p{0.98\\textwidth}@{}}{\\footnotesize",
    "\\textit{Note.} The preregistered-exclusion specification removes four",
    "participants who failed the end-of-survey response-quality check.",
    "Length-controlled estimates are intercepts from",
    "$\\Delta Y = \\alpha + \\beta\\,\\Delta\\mathrm{Words} + \\epsilon$,",
    "estimated on the included participants ($n=196$).}",
    "\\end{tabularx}",
    "\\caption{Human-study robustness and length-controlled estimates. Point estimates",
    "are reported with 95\\% confidence intervals in brackets.}",
    "\\label{tab:length_controls}",
    "\\end{table*}"
  ),
  path("tables", "exp_human_robustness.tex")
)

message(
  "Wrote tables/exp_human_robustness.{csv,tex} (",
  length(prereg_exclude_ids),
  " preregistered paraphrase exclusions)."
)

print(exp_robustness_csv)

message("\n=== human experiment outcomes ===")
print(exp_robustness_csv %>% select(Outcome, `Raw Estimates`))

## Receptiveness sds -------------------------------------------------------
message("\n=== Base experimental receptiveness diff ===")
mean(exp_prereg$rec_z_base[exp_prereg$provenance == "Model"]) -
  mean(exp_prereg$rec_z_base[exp_prereg$provenance == "Human"]) 

## Preference vs baseline receptiveness --------------------------

message("\n=== Main text: preference gap slope vs original receptiveness (item-level) ===")
exp_prereg %>%
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
  n <- nrow(exp_prereg)
  k <- sum(exp_prereg$verdict >= 4)
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
  n <- nrow(exp_prereg)
  k <- sum(exp_prereg$verdict <= 2)
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

## Quality distributions by participant verdict ----------------------------

exp_qual <- exp_qual %>% 
  filter(!participant_id %in% prereg_exclude_ids) 

p_quality_by_verdict <- exp_qual %>%
  count(provenance, speaker, verdict_bin, quality = quality_f) %>%
  complete(provenance, speaker, quality, verdict_bin, fill = list(n = 0)) %>%
  group_by(provenance, speaker, verdict_bin) %>%
  mutate(share = n / sum(n)) %>%
  ungroup() %>%
  filter(verdict_bin != "Unsure") %>%
  ggplot(aes(x = quality, y = share, fill = speaker)) +
  geom_col(position = position_dodge(width = 0.9), width = 0.85) +
  facet_grid(provenance ~ verdict_bin) +
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
    legend.background = element_blank(),
    strip.background = element_blank()
  ) +
  scale_fill_discrete(limits = c("Original", "Rewrite"))

ggsave(
  path("plots", "appendix", "quality_by_verdict.pdf"),
  p_quality_by_verdict,
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

p_verdicts <- exp_prereg %>%
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

## Eligible comments -------------------------------------------------------
N_aita <- 2000L

message("\n=== Supplement: AITA human-comment eligibility filter (2000 → 1892) ===")
{
  aita_posts <- read_csv(path("data", "aita", "AITA-YTA.csv")) %>%
    rename(row_idx = ...1) %>%
    mutate(
      top_comment = str_trim(as.character(top_comment)),
      excluded_removed = tolower(top_comment) %in% c("[removed]", "[deleted]"),
      excluded_short = !excluded_removed &
        (top_comment == "" | nchar(top_comment) < 15L),
      eligible = !excluded_removed & top_comment != "" & nchar(top_comment) >= 15L
    )

  stopifnot(
    nrow(aita_posts) == N_aita,
    sum(aita_posts$eligible) == length(fig2_expanded_row_idx),
    setequal(
      aita_posts$row_idx[aita_posts$eligible],
      fig2_expanded_row_idx
    )
  )

  aita_posts %>%
    summarize(
      n_corpus = n(),
      n_removed_or_deleted = sum(excluded_removed),
      n_fewer_than_15_chars = sum(excluded_short),
      n_excluded = sum(!eligible),
      n_eligible = sum(eligible)
    )
}

## Eligible comments by speaker (crowd and model say YTA) ---------------------

message("\n=== Supplement: Number of eligible comments by model")

read_csv(
  path("data", "aita_sycophancy_scores.csv")
) %>%
  filter(speaker != "GPT-5", speaker != "Rewrite") %>%
  distinct(speaker, row_idx) %>%
  group_by(speaker) %>%
  summarize(n = n())

## Yeomans dataset size --------------

message("\n=== Supplement: Number of training examples in Yeomans")

nrow(hear_train)

## HEAR Model Coefs--------------

message("\n=== Supplement: HEAR Model Coefs")

avg_coefs_df <- do.call(rbind, hear_coefs) %>%
  colMeans() |>
  data.frame(estimate = _)
avg_coefs_df


## Other experimental results -----------------------------------------------------

message("\n=== human experiment outcomes (length controlled) ===")
print(exp_robustness_csv %>% select(-`Raw Estimates`))


