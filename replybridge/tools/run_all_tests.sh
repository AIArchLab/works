#!/usr/bin/env bash
#  repo 
set -u
cd "$(dirname "$0")/.."
mkdir -p out
LOG=out/test_run_$(date -u +%Y%m%dT%H%M%SZ).log
: > "$LOG"

run() {
  local name="$1"; shift
  echo "### $name" | tee -a "$LOG"
  timeout 300 python3 "$@" 2>&1 | tee -a "$LOG"
  echo | tee -a "$LOG"
}

echo "=== ReplyBridge test run $(date -u +%FT%TZ) ===" | tee -a "$LOG"
for t in tests/test_channels.py tests/test_policy.py tests/test_ai.py tests/test_ledger.py; do
  [ -f "$t" ] && run "$t" "$t" || echo "SKIP $t (not present)" | tee -a "$LOG"
done
run "tests/e2e.py" tests/e2e.py
echo "log -> $LOG"
grep -E "PASS[[:space:]]*:|TOTAL:|=== [0-9]+/[0-9]+ PASS|FAILED CASES|ALL GREEN" "$LOG" || true
