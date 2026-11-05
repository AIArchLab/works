# BRIDGE-AUTO-01: Sender-Side Runner (De-identified)

## Overview
This is the de-identified sender-side runner for BRIDGE-AUTO-01 two-round
automated wake test. The runner automates:
1. Creating a unique-marked task in GPAI inbox (GitHub repo)
2. Sending a BRIDGE-AUTO message to GPAI via local CDP (Chrome DevTools Protocol)
3. Polling the repo for GPAI's response with matching marker
4. Recording round result

## Target Conversation
- Platform: GPAI (gpai.app/chat)
- Session ID: REDACTED (local config only)
- CDP: loopback only (port from local config, not public)

## Deployment
- Host: DSH host (Windows)
- Schedule: DSH schedule_create (managed, 2 rounds, >=60s interval)
- Runner: Node.js (bridge-auto-runner.mjs)
- Config: bridge-auto-config.json (local, contains token — NOT committed)

## De-identification Notes
- GitHub token: from local secrets file, not in source
- CDP port: from local config, not hardcoded
- Chrome profile: from local config, not in source
- GPAI session ID: from local CDP tab discovery, not in source
- All paths: from local config or CLI args

## Round Protocol
Each round:
1. Generate unique marker: BRIDGE-AUTO-01-R{N}-{timestamp}-{random}
2. PUT task file to inbox/gpai/{marker-slug}.json
3. Connect to GPAI tab via CDP (loopback)
4. Type BRIDGE-AUTO message with marker via execCommand
5. Click send button (aria-label="送出")
6. Verify input cleared (message sent)
7. Poll inbox/dsh-sd/ and bridge/wake-tests/ for matching marker
8. Record round result to local log + repo (if applicable)

## Inter-round Interval
Minimum 60 seconds between rounds. Serial execution (no parallel).

## Safety
- If GPAI tab not found → blocked, no retry
- If CDP connection fails → blocked, no retry
- If input not cleared after send → blocked (possible send failure)
- If login expired → blocked (no bypass)
- If session busy (generating) → wait, do not override input
- No blind resending: check target conversation/result first
