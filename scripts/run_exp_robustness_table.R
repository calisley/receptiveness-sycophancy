#!/usr/bin/env Rscript
# Regenerate tables/exp_human_robustness.{csv,tex} without running all of analysis.R.

suppressPackageStartupMessages({
  library(fs)
  library(tidyverse)
  library(jsonlite)
})

exp <- read_csv(path("data", "experiment", "responses.csv"), show_col_types = FALSE) %>%
  mutate(
    item_id = factor(item_id),
    order_ab = factor(order_ab, levels = c("ab", "ba")),
    provenance = factor(
      origin,
      levels = c("human", "model"),
      labels = c("Human", "Model")
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
    words_delta = n_words_rewrite - n_words_base
  )

exp_len <- exp %>%
  left_join(exp_items %>% select(item_id, words_delta), by = "item_id")

lines <- readLines("analysis.R")
start <- which(grepl("^# Table S7: Length Controls", lines))
end <- which(grepl("^# Appendix", lines))[1]
eval(parse(text = lines[start:(end - 1)]), envir = environment())
