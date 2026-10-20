# Nightly analysis logs — 2026-10-20 UTC

Captured from the `alpaca-trading-agent-web` container for the overnight run spanning **2026-10-20 14:00 UTC to 2026-10-20 20:19 UTC** (2026-10-21 01:00–07:19 in Sydney).

## Contents

- `*/TradingAgentsStrategy_logs/runs/*.json` — 44 individual audit logs containing prompts, node execution events, agent outputs, snapshots, run configuration, and final signals.
- `*/TradingAgentsStrategy_logs/full_states_log.json` — the consolidated final state for each of the seven analyzed symbols.
- `container.log` — timestamped Docker stdout/stderr captured from 2026-10-20 13:45–20:25 UTC, covering the full run window.

## Run summary

| Symbol | Runs | Result |
| --- | ---: | --- |
| AMD | 7 | All completed; final signal HOLD |
| AMZN | 6 | All completed; final signal HOLD |
| MCD | 6 | All completed; final signal HOLD |
| MSFT | 6 | All completed; final signal HOLD |
| NVDA | 7 | All completed; final signal HOLD |
| SPCX | 6 | All completed; final signal HOLD |
| TSLA | 6 | All completed; final signal HOLD |
| **Total** | **44** | **0 run-level error events** |

The audit JSON contains 572 prompt events, 660 node-execution events, and 792 agent-output events. The container log also records repeated Alpaca asset-search response validation errors around 14:02 UTC; these did not prevent the symbol analyses from completing.

The run logger redacts credential fields in persisted configuration. The captured files were scanned for common API-key patterns and account identifiers before commit.
