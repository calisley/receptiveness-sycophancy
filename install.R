#!/usr/bin/env Rscript
# Install the packages analysis.R loads. Tested on R 4.6.0.
#
#   Rscript install.R

Sys.setenv(LANG = Sys.getenv("LANG", "en_US.UTF-8"))
invisible(Sys.setlocale("LC_ALL", "en_US.UTF-8"))

repos <- "https://cloud.r-project.org"
need <- c(
  fs = "2.1.0",
  tidyverse = "2.0.0",
  cowplot = "1.2.0",
  jsonlite = "2.0.0",
  patchwork = "1.3.2",
  politeness = "0.9.4"
)

ip <- installed.packages()
missing <- names(need)[!names(need) %in% rownames(ip)]
if (length(missing)) {
  message("Installing: ", paste(missing, collapse = ", "))
  install.packages(missing, repos = repos)
}

ip <- installed.packages()
still <- names(need)[!names(need) %in% rownames(ip)]
if (length(still)) {
  stop("Failed to install: ", paste(still, collapse = ", "))
}

for (pkg in names(need)) {
  have <- ip[pkg, "Version"]
  if (!identical(have, need[[pkg]])) {
    message(
      sprintf("note: %s is %s (paper used %s)", pkg, have, need[[pkg]])
    )
  }
}

message("R packages ready.")
