#!/bin/zsh
# Add the final runs' household parts into one result per configuration.
# usage: scripts/combine_final.sh <parts> <seed>
set -eu
P=${1:?parts}; S=${2:?seed}
cd ${0:A:h}/..
for cfg in "2017 plain" "2017 health" "2025 plain" "2025 health"; do
  y=${cfg% *}; m=${cfg#* }
  .venv/bin/python -m cliffs2017.combine results/parts/run_${y}_${m}_p${P}_*_s${S}.json \
    --out results/final_${y}_${m}.json
done
.venv/bin/python scripts/render_results.py results/final_*.json > results/summary.md
