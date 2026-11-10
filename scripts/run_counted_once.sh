#!/bin/zsh
# The counted-once checks (scripts/counted_once.py) for the final runs counting
# health coverage: one job per household part, then, once a year's parts are
# all done, a combine into results/counted_once/once_<year>.json. Finished
# parts are skipped, so a rerun resumes.
# usage: scripts/run_counted_once.sh <parts> <seed> <part indices, comma-separated> [years]
#   years default to 2017,2025
#   e.g. scripts/run_counted_once.sh 4 0 0,1 & scripts/run_counted_once.sh 4 0 2,3
# Set CLIFFS_RUNNER or a .runner file to queue the runs (scripts/runner.zsh).
set -u
P=${1:?parts}; S=${2:?seed}; I=${3:?part indices}
Y=${4:-2017,2025}
cd ${0:A:h}/..
source scripts/runner.zsh
mkdir -p results/counted_once/parts logs
for y in ${(s:,:)Y}; do
  for i in ${(s:,:)I}; do
    out=results/counted_once/parts/once_${y}_p${P}_${i}_s${S}.json
    if [ -s $out ]; then echo "$(date -u +%FT%TZ) skip $out (done)" | tee -a logs/counted_once.log; continue; fi
    echo "$(date -u +%FT%TZ) start once $y part $i/$P s=$S" | tee -a logs/counted_once.log
    run cliffs-once-$y-p$i .venv/bin/python scripts/counted_once.py \
      --year $y --parts $P --part $i --seed $S \
      > logs/counted_once_${y}_p${P}_${i}_s${S}.log 2>&1
    rc=$?
    echo "$(date -u +%FT%TZ) end once $y part $i rc=$rc" | tee -a logs/counted_once.log
  done
  files=(results/counted_once/parts/once_${y}_p${P}_*_s${S}.json(N))
  if (( ${#files} == P )); then
    .venv/bin/python scripts/counted_once.py --combine $files 2>&1 | tee -a logs/counted_once.log
  fi
done
