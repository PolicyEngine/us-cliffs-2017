#!/bin/zsh
# Add the final runs' household parts into one result per configuration, then
# check part 0 of each run without health coverage against the subsample run
# over the same households (scripts/check_part_scaling.py), where one exists.
# usage: scripts/combine_final.sh <parts> <seed>
set -eu
P=${1:?parts}; S=${2:?seed}
cd ${0:A:h}/..
for cfg in "2017 plain" "2017 health" "2025 plain" "2025 health"; do
  y=${cfg% *}; m=${cfg#* }
  .venv/bin/python -m cliffs2017.combine results/parts/run_${y}_${m}_p${P}_*_s${S}.json \
    --out results/final_${y}_${m}.json
done
# results/ and results/parts/ hold the main runs; results/csfp/ and
# results/parts/csfp/ the runs that count CSFP (scripts/run_batch.sh makes the
# subsample runs, with CSFP=keep for the second folder).
f=$(.venv/bin/python -c "print(1 / $P)")
for dir in results results/csfp; do
  for y in 2017 2025; do
    sub=$dir/run_${y}_plain_f${f}_s${S}.json
    part=results/parts${dir#results}/run_${y}_plain_p${P}_0_s${S}.json
    if [ -s $sub ] && [ -s $part ]; then
      echo "part 0 against $sub:"
      .venv/bin/python scripts/check_part_scaling.py $P $part $sub
    fi
  done
done
# The CSFP sensitivity: 2025 runs on the model's own benefit list, from
# CSFP=keep scripts/run_final.sh (cliffs2017/benefits.py).
for m in plain health; do
  files=(results/parts/csfp/run_2025_${m}_p${P}_*_s${S}.json(N))
  if (( ${#files} == P )); then
    mkdir -p results/csfp
    .venv/bin/python -m cliffs2017.combine $files --out results/csfp/final_2025_${m}.json
  fi
done
.venv/bin/python scripts/render_results.py results/final_*.json \
  --csfp results/csfp/final_*.json(N) > results/summary.md
