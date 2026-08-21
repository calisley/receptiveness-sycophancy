#!/usr/bin/env bash
# Fresh Python venv + R packages.
set -euo pipefail
cd "$(dirname "$0")"
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

if ! command -v python3 >/dev/null; then
  echo "Need python3 (3.12)." >&2
  exit 1
fi
if ! command -v Rscript >/dev/null; then
  echo "Need R / Rscript (4.3+; paper used 4.6.0)." >&2
  exit 1
fi

python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt

Rscript install.R

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Wrote .env from .env.example — add API keys before generation."
fi

echo
echo "Ready."
echo "  source .venv/bin/activate"
echo "  Rscript analysis.R"
