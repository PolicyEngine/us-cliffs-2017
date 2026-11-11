#!/bin/zsh
# Cliff counts for other changes in earnings (scripts/earnings_changes.py), part by part.
# Each process runs one raise and the cut of the same size: memory grows with the branches
# one process builds, and two changes (four branches) match the final runs' footprint (about
# 11 GB). Changes already written are skipped, so a rerun resumes. Set CLIFFS_RUNNER or a
# .runner file to queue the runs (scripts/runner.zsh).
# Then: python scripts/earnings_changes_summary.py [--years 2017]
# usage: scripts/run_earnings_changes.sh <years, comma-separated> <part indices, comma-separated>
#   e.g. scripts/run_earnings_changes.sh 2017,2025 0,1 & scripts/run_earnings_changes.sh 2017,2025 2,3
set -u
Y=${1:?years}; I=${2:?part indices}
BATCHES=(+1000,-1000 +2000,-2000 +5000,-5000 +1%,-1% +10%,-10%)
cd ${0:A:h}/..
source scripts/runner.zsh
mkdir -p logs
for y in ${(s:,:)Y}; do
  for i in ${(s:,:)I}; do
    n=0
    for b in $BATCHES; do
      n=$((n+1))
      if [ "$(.venv/bin/python scripts/earnings_changes.py --year $y --part $i --changes $b --todo)" = 0 ]; then
        echo "$(date -u +%FT%TZ) skip $y part $i batch $n ($b): done" | tee -a logs/earnings_changes.log; continue
      fi
      echo "$(date -u +%FT%TZ) start $y part $i batch $n ($b)" | tee -a logs/earnings_changes.log
      run cliffs-changes-$y-p$i-b$n .venv/bin/python scripts/earnings_changes.py --year $y --part $i --changes $b \
        >> logs/earnings_changes_${y}_p4_${i}_s0.log 2>&1
      rc=$?
      echo "$(date -u +%FT%TZ) end $y part $i batch $n rc=$rc" | tee -a logs/earnings_changes.log
    done
  done
done
