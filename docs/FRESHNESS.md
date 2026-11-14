# Source freshness diagnostics

Four optional diagnostic entities are disabled by default:

- Telemetry freshness
- GPS freshness
- Last successful telemetry fetch
- Last successful GPS fetch

These supplement, not replace, existing vehicle/GPS last-updated entities. Enable
only the diagnostics you want on the vehicle's entity page after installing a
reviewed version. Existing entities, automations and API cadence are unchanged.

## Meaning

`fresh` means the source timestamp is no older than two effective polling
intervals, with a five-minute minimum. Effective telemetry cadence includes the
existing AC-charging slowdown. `stale` means old data, **not a vehicle fault,
failed command, unlocked car or offline service**. Parked/asleep cars can retain
old data normally; no sleeping state is inferred from age. `paused` means polling
is intentionally disabled. MQTT may still deliver data while polling is paused;
age remains visible as an attribute, but paused is not a claim of confirmed fresh
data. Missing, naive, pre-2000 or future source timestamps yield `unknown`.

Telemetry and GPS are evaluated separately. GPS freshness uses the raw parsed GPS
timestamp, without shifting old fixes toward newer telemetry timestamps. Thus
freshness can be unknown while the existing GPS timestamp sensor applies a
display-time correction. Do not guess whether a timezone-shifted fix is fresh.

Each source's successful-fetch timestamp advances only after that source's fetch
returns successfully (including explicit fetch services). It does not advance on
failed/unsupported/skipped fetches, success of another source, state pushes or
optimistic command projections. A fetch may return old vehicle data: successful
fetch and fresh data are intentionally different concepts. The underlying library
can deliver a requested result through MQTT or HTTP; this is not an HTTP-only
transport sensor. These process-local timestamps reset to unknown on reload and
are not restored as proof of a new successful connection.

A source timestamp does **not** prove that every field in the merged snapshot was
individually refreshed, nor that an optimistic lock/climate command physically
completed. No existing automation is automatically blocked or changed. A caller
can choose to require fresh telemetry before interpreting a lock/battery value,
and fresh GPS separately before using a location.

Freshness attributes include data age in seconds, threshold seconds and polling
enabled. A local once-per-minute timer recomputes age for enabled freshness
entities, even after a failed refresh. It makes no network requests, sends no
commands, and is unsubscribed with the entity. Last-success timestamps do not
require this timer. No payloads, credentials, coordinates or new log bodies are
exposed by these diagnostics.

## Offline verification

Use Python 3.14, Home Assistant 2026.11.1, pyBYD 0.0.80, pytest and pytest-asyncio:

```sh
python -m pytest tests -q -o asyncio_default_fixture_loop_scope=function
ruff check .
black --check .
mypy .
```

71 tests pass, including 40 new cases, on HA 2026.11.1 (the owner's verified
version). Ruff and Black pass. Full runtime-environment Mypy is not green:
11 identical errors reproduce on clean upstream b48df61 with this HA/toolchain
(coordinator optional-data annotations, config-flow schemas/ignore and climate
deprecated/final properties). No new candidate type errors remain. Do not label
the runtime type check as passed or fix unrelated upstream issues in this PR.
In a separate Python 3.11 environment matching the upstream lint workflow's
tool-only installation, Ruff, Black and Mypy all pass. See LIVE-VALIDATION.md.

## Live validation and remaining coverage

Initial owner-approved installation, Core restart and four-sensor observations
are now documented in LIVE-VALIDATION.md. No vehicle commands or account
credentials were used by the contributor. Raw vehicle payloads and all live
edge-case transitions remain unverified. The checklist below distinguishes
completed happy-path observations from further optional validation:

1. Enable the four optional diagnostics. Check names, source/device association
   and normal non-negative ages against existing timestamps.
2. Observe normal polling and a parked period. Confirm an old response can have a
   new fetch time while old source data remains stale. Do not wake the car merely
   to prove the clock advances.
3. Check GPS and telemetry independently; compare with the official app without
   claiming app values are a universal freshness oracle.
4. Check pause/resume using existing integration controls only when approved.
   Verify paused versus unknown/stale and recovery when fresh data arrives.
5. Check disable/unload/reload cleanup and successful-fetch reset. Test failure
   and invalid timestamp cases with mocks, not by disrupting the live network.
6. Collect only redacted observations. Never attach VIN, account credentials,
   tokens, location or entire HA config/diagnostic payloads to a public PR.

Current status: automated checks, initial live happy-path validation and redacted
normal-polling debug logs complete. Live edge-case transitions remain unobserved.
