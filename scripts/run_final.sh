#!/bin/zsh
# Final runs: the four configurations on the full sample, split into disjoint
# household parts that each fit the heavy-run memory ceiling, with the
# by-program breakdown. Finished parts are skipped, so a rerun resumes.
# usage: scripts/run_final.sh <parts> <seed> <part indices, comma-separated>
#   e.g. scripts/run_final.sh 4 0 0,1 & scripts/run_final.sh 4 0 2,3
# Then: scripts/combine_final.sh <parts> <seed>
set -u
P=${1:?parts}; S=${2:?seed}; I=${3:?part indices}
cd ${0:A:h}/..
mkdir -p results/parts logs
for i in ${(s:,:)I}; do
  for cfg in "2017 plain" "2017 health" "2025 plain" "2025 health"; do
    y=${cfg% *}; m=${cfg#* }
    flags=(--decompose)
    [ $m = health ] && flags+=(--health)
    [ $y -lt 2018 ] && flags+=(--aca-before-2018)
    out=results/parts/run_${y}_${m}_p${P}_${i}_s${S}.json
    if [ -s $out ]; then echo "$(date -u +%FT%TZ) skip $out (done)" | tee -a logs/final.log; continue; fi
    echo "$(date -u +%FT%TZ) start $y $m part $i/$P s=$S" | tee -a logs/final.log
    ~/reviews/us-hub/scripts/heavy_run.sh cliffs-final-$y-$m-p$i .venv/bin/python -m cliffs2017.run \
      --year $y $flags --parts $P --part $i --seed $S --out $out \
      > logs/final_${y}_${m}_p${P}_${i}_s${S}.log 2>&1
    echo "$(date -u +%FT%TZ) end $y $m part $i rc=$?" | tee -a logs/final.log
  done
done
