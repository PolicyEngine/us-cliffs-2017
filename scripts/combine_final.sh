#!/bin/zsh
# Add the final runs' household parts into one result per configuration, check
# part 0 of each run without health coverage against the subsample run over the
# same households (scripts/check_part_scaling.py), and write results/summary.md.
# Each combine passes the settings its folder implies (--expect), so a part run
# under another setting fails here instead of landing in the wrong row.
# Exits 1 if a part-scaling check is missing, after writing everything else.
# usage: scripts/combine_final.sh <parts> <seed>
set -eu
P=${1:?parts}; S=${2:?seed}
cd ${0:A:h}/..
combine() {  # <out> <year> <health> <leave_out_csfp> <part files...>
  local out=$1 y=$2 h=$3 c=$4; shift 4
  local aca=false; [ $y -lt 2018 ] && aca=true
  .venv/bin/python -m cliffs2017.combine "$@" --out $out \
    --expect year=$y --expect health_benefits_in_net_income=$h \
    --expect aca_before_2018=$aca --expect leave_out_csfp=$c --expect decompose=true
}
# results/ and results/parts/ hold the main runs, which leave CSFP out from 2024
# (cliffs2017/benefits.py); results/csfp/ and results/parts/csfp/ the 2025 runs
# that count it as the model does (CSFP=keep scripts/run_final.sh).
for cfg in "2017 plain" "2017 health" "2025 plain" "2025 health"; do
  y=${cfg% *}; m=${cfg#* }
  h=false; [ $m = health ] && h=true
  c=false; [ $y -ge 2024 ] && c=true
  combine results/final_${y}_${m}.json $y $h $c results/parts/run_${y}_${m}_p${P}_*_s${S}.json
done
for m in plain health; do
  files=(results/parts/csfp/run_2025_${m}_p${P}_*_s${S}.json(N))
  h=false; [ $m = health ] && h=true
  if (( ${#files} == P )); then
    mkdir -p results/csfp
    combine results/csfp/final_2025_${m}.json 2025 $h false $files
  fi
done
# scripts/run_batch.sh makes the subsample runs (CSFP=keep for results/csfp/).
f=$(.venv/bin/python -c "print(1 / $P)")
missing=0
for dir in results results/csfp; do
  for y in 2017 2025; do
    [ $dir = results/csfp ] && [ $y -lt 2024 ] && continue
    sub=$dir/run_${y}_plain_f${f}_s${S}.json
    part=results/parts${dir#results}/run_${y}_plain_p${P}_0_s${S}.json
    if [ -s $sub ] && [ -s $part ]; then
      echo "part 0 against $sub:"
      .venv/bin/python scripts/check_part_scaling.py $P $part $sub
    else
      echo "MISSING part-scaling check: need $part and $sub (scripts/run_batch.sh $f $S)" >&2
      missing=1
    fi
  done
done
.venv/bin/python scripts/render_results.py results/final_*.json \
  --csfp results/csfp/final_*.json(N) > results/summary.md
exit $missing
