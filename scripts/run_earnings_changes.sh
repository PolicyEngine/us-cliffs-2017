#!/bin/zsh
# Cliff counts for other changes in earnings (scripts/earnings_changes.py), part by part.
# Finished parts are skipped, so a rerun resumes. Set CLIFFS_RUNNER or a .runner file to
# queue the runs (scripts/runner.zsh). Then: python scripts/earnings_changes_summary.py
# usage: scripts/run_earnings_changes.sh <years, comma-separated> <part indices, comma-separated>
#   e.g. scripts/run_earnings_changes.sh 2017,2025 0,1 & scripts/run_earnings_changes.sh 2017,2025 2,3
set -u
Y=${1:?years}; I=${2:?part indices}
cd ${0:A:h}/..
source scripts/runner.zsh
mkdir -p results/earnings_changes/parts logs
for y in ${(s:,:)Y}; do
  for i in ${(s:,:)I}; do
    out=results/earnings_changes/parts/changes_${y}_p4_${i}_s0.json
    if [ -s $out ]; then echo "$(date -u +%FT%TZ) skip $out (done)" | tee -a logs/earnings_changes.log; continue; fi
    echo "$(date -u +%FT%TZ) start $y part $i" | tee -a logs/earnings_changes.log
    run cliffs-changes-$y-p$i .venv/bin/python scripts/earnings_changes.py --year $y --part $i \
      > logs/earnings_changes_${y}_p4_${i}_s0.log 2>&1
    rc=$?
    echo "$(date -u +%FT%TZ) end $y part $i rc=$rc" | tee -a logs/earnings_changes.log
  done
done
