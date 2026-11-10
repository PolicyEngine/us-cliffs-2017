#!/bin/zsh
# Full-sample Medicaid state totals (cliffs2017.medicaid) for the health runs:
# per-state sums over each disjoint household part, under the configuration's
# own policy, then their total. Finished parts are skipped, so a rerun resumes.
# usage: scripts/medicaid_totals.sh <parts> <seed> [years, comma-separated; default 2017,2025]
#   e.g. scripts/medicaid_totals.sh 4 0 2017 & scripts/medicaid_totals.sh 4 0 2025
set -u
P=${1:?parts}; S=${2:?seed}; Y=${3:-2017,2025}
cd ${0:A:h}/..
mkdir -p results/medicaid logs
for y in ${(s:,:)Y}; do
  flags=()
  [ $y -lt 2018 ] && flags+=(--aca-before-2018)
  for i in $(seq 0 $((P - 1))); do
    out=results/medicaid/sums_${y}_p${P}_${i}_s${S}.json
    if [ -s $out ]; then echo "$(date -u +%FT%TZ) skip $out (done)" | tee -a logs/medicaid.log; continue; fi
    echo "$(date -u +%FT%TZ) start medicaid sums $y part $i/$P s=$S" | tee -a logs/medicaid.log
    ~/reviews/us-hub/scripts/heavy_run.sh cliffs-medicaid-$y-p$i .venv/bin/python -m cliffs2017.medicaid sums \
      --year $y $flags --parts $P --part $i --seed $S --out $out \
      > logs/medicaid_${y}_p${P}_${i}_s${S}.log 2>&1
    rc=$?
    echo "$(date -u +%FT%TZ) end medicaid sums $y part $i rc=$rc" | tee -a logs/medicaid.log
  done
  .venv/bin/python -m cliffs2017.medicaid combine --out results/medicaid/totals_${y}_p${P}_s${S}.json \
    results/medicaid/sums_${y}_p${P}_*_s${S}.json 2>&1 | tee -a logs/medicaid.log
done
