#!/bin/zsh
# The runs without health coverage on one household subsample, at weights
# scaled to the full population. scripts/check_part_scaling.py compares part 0
# of the final runs with the quarter-sample run (fraction 0.25).
# usage: scripts/run_batch.sh <fraction> [seed]
# As in run_final.sh, runs from 2024 leave out the Commodity Supplemental Food
# Program (cliffs2017/benefits.py); CSFP=keep makes only the 2025 run, on the
# model's own benefit list, in results/csfp/.
# Set CLIFFS_RUNNER or a .runner file to queue the runs (scripts/runner.zsh).
set -u
case "${CSFP:-}" in
  ""|keep) ;;
  *) echo "CSFP must be unset or keep, not '$CSFP'" >&2; exit 2 ;;
esac
F=${1:?fraction}; S=${2:-0}
cd ${0:A:h}/..
source scripts/runner.zsh
dir=results
[ "${CSFP:-}" = keep ] && dir=results/csfp
mkdir -p $dir logs
for y in 2017 2025; do
  [ "${CSFP:-}" = keep ] && [ $y -lt 2024 ] && continue
  flags=()
  [ $y -lt 2018 ] && flags+=(--aca-before-2018)
  [ $y -ge 2024 ] && [ "${CSFP:-}" != keep ] && flags+=(--leave-out-csfp)
  out=$dir/run_${y}_plain_f${F}_s${S}.json
  echo "$(date -u +%FT%TZ) start $y plain${CSFP:+ csfp} f=$F s=$S" | tee -a logs/batch.log
  run cliffs-$y-plain${CSFP:+-csfp} .venv/bin/python -m cliffs2017.run --year $y $flags --fraction $F --seed $S --out $out \
    > logs/run_${y}_plain_f${F}_s${S}${CSFP:+_csfp}.log 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) end $y plain${CSFP:+ csfp} rc=$rc" | tee -a logs/batch.log
done
