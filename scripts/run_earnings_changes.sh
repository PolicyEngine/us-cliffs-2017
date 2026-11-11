#!/bin/zsh
# Cliff counts for other changes in earnings (scripts/earnings_changes.py), part by part.
# Each process runs one raise and the cut of the same size: memory grows with the branches
# one process builds, and two changes (four branches) match the final runs' footprint (about
# 11 GB). Changes already written are skipped, so a rerun resumes. Set CLIFFS_RUNNER or a
# .runner file to queue the runs (scripts/runner.zsh).
# A part stops at its first failed batch. If its $1,000 raise didn't reproduce the committed
# part, the script skips the part until you delete that change's file and rerun.
# Then: python scripts/earnings_changes_summary.py [--years 2017]
# usage: scripts/run_earnings_changes.sh <years, comma-separated> <part indices, comma-separated>
#   e.g. scripts/run_earnings_changes.sh 2017,2025 0,1 & scripts/run_earnings_changes.sh 2017,2025 2,3
set -u
Y=${1:?years}; I=${2:?part indices}
BATCHES=(+1000,-1000 +2000,-2000 +5000,-5000 +1%,-1% +10%,-10%)
cd ${0:A:h}/..
source scripts/runner.zsh
mkdir -p logs

# How many of a batch's changes aren't written yet, or "failed" if the part's $1,000 raise is written
# and didn't reproduce the committed part. Reads only cliffs2017.changes (numpy and pandas), not the
# model; scripts/earnings_changes.py writes the files and skips the changes already written in any case.
batch_state() {
  .venv/bin/python -c '
import json, sys
from pathlib import Path
from cliffs2017.changes import parse
year, part, batch = sys.argv[1:]
folder = Path("results/earnings_changes/parts") / f"changes_{year}_p4_{part}_s0"
base = folder / "raise_1000.json"
if base.exists() and json.loads(base.read_text()).get("reproduces_committed_part") is not True:
    print("failed")
else:
    print(sum(not (folder / f"{parse(text).key}.json").exists() for text in batch.split(",")))
' $1 $2 $3
}

for y in ${(s:,:)Y}; do
  for i in ${(s:,:)I}; do
    n=0
    for b in $BATCHES; do
      n=$((n+1))
      state=$(batch_state $y $i $b)
      if [ "$state" = failed ]; then
        echo "$(date -u +%FT%TZ) stop $y part $i: its \$1,000 raise doesn't reproduce the committed part (logs/earnings_changes_${y}_p4_${i}_s0.log); delete results/earnings_changes/parts/changes_${y}_p4_${i}_s0/raise_1000.json to rerun it" | tee -a logs/earnings_changes.log
        break
      fi
      if [ "$state" = 0 ]; then
        echo "$(date -u +%FT%TZ) skip $y part $i batch $n ($b): done" | tee -a logs/earnings_changes.log; continue
      fi
      echo "$(date -u +%FT%TZ) start $y part $i batch $n ($b)" | tee -a logs/earnings_changes.log
      run cliffs-changes-$y-p$i-b$n .venv/bin/python scripts/earnings_changes.py --year $y --part $i --changes $b \
        >> logs/earnings_changes_${y}_p4_${i}_s0.log 2>&1
      rc=$?
      echo "$(date -u +%FT%TZ) end $y part $i batch $n rc=$rc" | tee -a logs/earnings_changes.log
      if [ $rc -ne 0 ]; then
        echo "$(date -u +%FT%TZ) stop $y part $i: batch $n failed; rerun the script to resume from it" | tee -a logs/earnings_changes.log
        break
      fi
    done
  done
done
