---
name: verify
description: Run targeted, non-destructive validation after repository changes and report exact evidence; do not use it to claim unexecuted integration or live-audio tests passed.
---

# Verification

Select checks proportional to the change and inspect, where available:

- syntax and compilation
- imports and dependency availability
- unit tests and deterministic smoke tests
- audio device diagnostics without starting capture unless authorized
- configuration validation
- Git status, diff, and whitespace errors
- secret leakage in the changed content
- Windows and macOS regressions
- documentation consistency

Report every relevant check as exactly one of:

- `PASS` — executed and satisfied its criterion
- `FAIL` — executed and did not satisfy its criterion
- `NOT RUN` — relevant but not executed, with the reason
- `NOT APPLICABLE` — unrelated to the change

Never turn a missing dependency into an unrelated project failure, and never report an unexecuted test as passing. Do not call external APIs, capture live audio, synthesize speech, download models, or change the environment merely to make validation green unless explicitly authorized.
