# Live validation — 14 November 2026

Observed on a BYD Sealion 7 with Home Assistant 2026.11.1, pyBYD 0.0.80 and integration
0.0.93 plus this prototype. All values below are redacted transcriptions of
owner-supplied UI evidence, not fabricated logs. No VIN, account, location or raw
API payload is included. Screenshots themselves are retained privately, not
attached to a public PR without review.

## Test flow and observed result

1. Read-only preflight confirmed all four affected original files matched
   upstream, correct dependency versions and no existing freshness helper.
2. Owner ran the reviewed source-only installer, which verified backups/original
   hashes and new payloads. No restart was automated.
3. Owner restarted HA Core and confirmed HA returned. Enabled only the four new
   optional diagnostic entities, leaving other settings and polling unchanged.
4. With ordinary polling, all four entities displayed values. Last successful
   telemetry fetch advanced from approximately 20:41 to 20:43 local time; GPS
   separately displayed approximately 20:41. Do not infer exact fetch seconds from
   rounded UI labels or treat update events as precise raw source timestamps.
5. Details panels around 20:45 showed:

| Diagnostic | State | Data age seconds | Threshold seconds | Polling enabled |
|---|---|---:|---:|---|
| Telemetry | Fresh |60|480|true|
| GPS | Fresh |150|600|true|

Both comparisons agree with the implemented freshness rule. The configured
telemetry interval was 60s, but threshold 480s implies effective 240s cadence, which
is consistent with the existing AC-charging slowdown rule. Charging state was
not captured, so this is not independent proof the car was charging. GPS
threshold 600s matches two configured 300s intervals.

Both freshness panels had last_changed 20:41:28 and last_updated 20:44:28. This
confirms attribute updates while Fresh stays unchanged; it is not a live network
trace proving a particular update originated solely from the local timer.

## Limits

- Happy-path registration, enablement, timestamps, independent source freshness
  and attribute presentation verified live.
- Live stale→fresh, pause/resume, outage/recovery and unload transitions have NOT
  all been exercised. Covered by automated fixtures, not claimed as live results.
- No vehicle action commands, forced refresh, deliberate outage or polling
  interval changes were requested for this test.
- Existing GPS timestamp display may normalize timestamps; raw backend GPS data
  was not exported. The new freshness diagnostic deliberately uses raw parsed age.
- No new cloud polling follows from the source diff/local timer tests. No live
  request-rate comparison was performed.

## Local validation environments

- Runtime environment: Python 3.14, HA 2026.11.1, pyBYD 0.0.80: 71 tests pass, Ruff/
  Black pass. Full Mypy has 11 errors reproduced identically in clean upstream
  with these runtime dependencies; zero new errors.
- Upstream lint-workflow-style environment: Python 3.11 with Black/Ruff/Mypy only,
  no Home Assistant installation: full Ruff, Black and Mypy pass (21 source files).
  This matches lint.yaml's installation pattern; it is **local CI parity**, not
  proof a remote GitHub Actions run or HACS/hassfest validation passed.

Remaining before marking the PR ready for review: full redacted end-to-end debug
logs requested by the contribution guidelines, contributor review and remote
checks. UI observations above are not presented as debug logs. The unobserved
live edge cases remain explicitly documented rather than claimed as completed.
