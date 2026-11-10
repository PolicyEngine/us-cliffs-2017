#!/bin/zsh
# Run the four headline configurations on one household sample.
# usage: scripts/run_batch.sh <fraction> [seed]
set -u
F=${1:?fraction}; S=${2:-0}
cd ${0:A:h}/..
mkdir -p results logs
for cfg in "2017 plain" "2017 health" "2025 plain" "2025 health"; do
  y=${cfg% *}; m=${cfg#* }
  flags=()
  [ $m = health ] && flags+=(--health)
  [ $y -lt 2018 ] && flags+=(--aca-before-2018)
  out=results/run_${y}_${m}_f${F}_s${S}.json
  echo "$(date -u +%FT%TZ) start $y $m f=$F s=$S" | tee -a logs/batch.log
  ~/reviews/us-hub/scripts/heavy_run.sh cliffs-$y-$m .venv/bin/python -m cliffs2017.run --year $y $flags --fraction $F --seed $S --out $out > logs/run_${y}_${m}_f${F}_s${S}.log 2>&1
  echo "$(date -u +%FT%TZ) end $y $m rc=$?" | tee -a logs/batch.log
done
