#!/bin/zsh
# Add the final runs' household parts into one result per configuration, then
# check part 0 of each run without health coverage against the quarter-sample
# run over the same households (scripts/check_part_scaling.py), where one exists.
# usage: scripts/combine_final.sh <parts> <seed>
set -eu
P=${1:?parts}; S=${2:?seed}
cd ${0:A:h}/..
for cfg in "2017 plain" "2017 health" "2025 plain" "2025 health"; do
  y=${cfg% *}; m=${cfg#* }
  .venv/bin/python -m cliffs2017.combine results/parts/run_${y}_${m}_p${P}_*_s${S}.json \
    --out results/final_${y}_${m}.json
done
for y in 2017 2025; do
  sub=results/run_${y}_plain_f$(.venv/bin/python -c "print(1 / $P)")_s${S}.json
  if [ -s $sub ]; then
    echo "part 0 against $sub:"
    .venv/bin/python scripts/check_part_scaling.py $P results/parts/run_${y}_plain_p${P}_0_s${S}.json $sub
  fi
done
.venv/bin/python scripts/render_results.py results/final_*.json > results/summary.md
