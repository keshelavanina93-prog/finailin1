# Retained event-time observations — NIN-27 foundation

A canonical enterprise stream must have an independently accepted policy version with `event_time_policy_version=event-time/1`, `late_policy=RETAIN_ONLY`, integer `allowed_lateness_seconds` (0–31536000), and integer `allowed_future_seconds` (0–86400). Those properties are governed through the existing canonical schema/proposal path. No company, source or policy identity is synthesized by ingestion.

`POST /v1/ontology/event-time/events` retains source event identity, UTC event time, server processing time, arrival sequence, exact stream/policy version, payload/hash, actor and policy boundary. Watermark is the largest prior event time for the exact stream version minus accepted lateness. Policy version changes therefore have an explicit separate watermark. Late events are retained with their original admission decision. Different content cannot reuse a stream event identity.

`GET /v1/ontology/event-time/streams/{id}/replay?known_at=...` replays retained admission decisions as of knowledge time, selecting the latest event per partition by `(event_time,event_id)`. `include_late=true` provides a separately labelled backfill observation view. Both are OBSERVED and non-authorizing; neither is a journal, report, certified value, financial transformation or replacement for NIN22 prerequisites. Replay is bounded to 10000 events and refuses truncation. Event payloads are source observations, not canonical business identities.

Focused PostgreSQL evidence: duplicate replay, conflicting identity refusal, late retention/watermark, deterministic tie ordering, historical reconstruction, explicit backfill, future-time refusal and cross-company denial passed. Migration019 applied; affected source checks passed. Existing unrelated ontology edits and Petroleum REFERENCE_ONLY quarantine preserved.

Integration evidence: affected mypy/Ruff and production build passed. Authenticated replay through the running web API returned BACKFILL_OBSERVATION, OBSERVED, three retained events, one late event, and current_use_authorized=false after API/web restart on the migrated database.

## Scheduled policy parity

Migration 033 aligns the database event-admission trigger with the shared current-effective version resolver. Publishing a future policy no longer interrupts admission under the still-effective policy. Publication heads remain the editing/conflict boundary; exact retained stream-version pins and version-specific watermarks remain unchanged.

The native `test_event_time.py` regression reproduced the former database refusal after scheduling a successor. After migration 033 it passed (2.44 seconds): current-policy admission and duplicate recovery succeed, the late watermark still uses the old 30-second policy rather than the scheduled 300-second policy, premature future-policy use is refused, and historical replay/backfill/isolation remain intact. Ruff passed. Fixtures are synthetic observed events, not live gas telemetry, accounting facts or certification.
