#!/bin/zsh
# The runs without health coverage on one household subsample, at weights
# scaled to the full population. scripts/check_part_scaling.py compares part 0
# of the final runs with the quarter-sample run (fraction 0.25).
# usage: scripts/run_batch.sh <fraction> [seed]
# Set CLIFFS_RUNNER or a .runner file to queue the runs (scripts/runner.zsh).
set -u
F=${1:?fraction}; S=${2:-0}
cd ${0:A:h}/..
source scripts/runner.zsh
mkdir -p results logs
for y in 2017 2025; do
  flags=()
  [ $y -lt 2018 ] && flags+=(--aca-before-2018)
  out=results/run_${y}_plain_f${F}_s${S}.json
  echo "$(date -u +%FT%TZ) start $y plain f=$F s=$S" | tee -a logs/batch.log
  run cliffs-$y-plain .venv/bin/python -m cliffs2017.run --year $y $flags --fraction $F --seed $S --out $out \
    > logs/run_${y}_plain_f${F}_s${S}.log 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) end $y plain rc=$rc" | tee -a logs/batch.log
done
