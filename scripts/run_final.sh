#!/bin/zsh
# Final runs: the four configurations on the full sample, split into disjoint
# household parts that each fit in about 11 GB of memory, with the by-program
# breakdown. Finished parts are skipped, so a rerun resumes.
# Health runs read the full-sample Medicaid totals from
# scripts/medicaid_totals.sh and wait for them: a part whose totals don't
# exist yet is skipped, and a rerun picks it up.
# usage: scripts/run_final.sh <parts> <seed> <part indices, comma-separated> [configurations]
#   configurations default to 2017-plain,2017-health,2025-plain,2025-health
#   e.g. scripts/run_final.sh 4 0 0,1 & scripts/run_final.sh 4 0 2,3
# Then: scripts/combine_final.sh <parts> <seed>
# Set CLIFFS_RUNNER or a .runner file to queue the runs (scripts/runner.zsh).
# From 2024 the model counts the Commodity Supplemental Food Program in
# household benefits and gives every eligible person a package, so runs for
# those years leave it out (cliffs2017/benefits.py) and count the benefits a
# 2017 run does. CSFP=keep runs the model's own list instead, into
# results/parts/csfp/, for the sensitivity in results/summary.md.
set -u
case "${CSFP:-}" in
  ""|keep) ;;
  *) echo "CSFP must be unset or keep, not '$CSFP'" >&2; exit 2 ;;
esac
P=${1:?parts}; S=${2:?seed}; I=${3:?part indices}
C=${4:-2017-plain,2017-health,2025-plain,2025-health}
cd ${0:A:h}/..
source scripts/runner.zsh
partdir=results/parts
[ "${CSFP:-}" = keep ] && partdir=results/parts/csfp
mkdir -p $partdir logs
for i in ${(s:,:)I}; do
  for cfg in ${(s:,:)C}; do
    y=${cfg%-*}; m=${cfg#*-}
    # CSFP=keep is a 2025 sensitivity: 2017 rules have no CSFP to keep.
    [ "${CSFP:-}" = keep ] && [ $y -lt 2024 ] && continue
    flags=(--decompose)
    [ $y -lt 2018 ] && flags+=(--aca-before-2018)
    [ $y -ge 2024 ] && [ "${CSFP:-}" != keep ] && flags+=(--leave-out-csfp)
    if [ $m = health ]; then
      totals=results/medicaid/totals_${y}_p${P}_s${S}.json
      if [ ! -s $totals ]; then
        echo "$(date -u +%FT%TZ) wait $y $m part $i: no $totals yet (scripts/medicaid_totals.sh)" | tee -a logs/final.log
        continue
      fi
      flags+=(--health --medicaid-totals $totals)
    fi
    out=$partdir/run_${y}_${m}_p${P}_${i}_s${S}.json
    if [ -s $out ]; then echo "$(date -u +%FT%TZ) skip $out (done)" | tee -a logs/final.log; continue; fi
    echo "$(date -u +%FT%TZ) start $y $m${CSFP:+ csfp} part $i/$P s=$S" | tee -a logs/final.log
    run cliffs-final-$y-$m-p$i${CSFP:+-csfp} .venv/bin/python -m cliffs2017.run \
      --year $y $flags --parts $P --part $i --seed $S --out $out \
      > logs/final_${y}_${m}_p${P}_${i}_s${S}${CSFP:+_csfp}.log 2>&1
    rc=$?
    echo "$(date -u +%FT%TZ) end $y $m${CSFP:+ csfp} part $i rc=$rc" | tee -a logs/final.log
  done
done
