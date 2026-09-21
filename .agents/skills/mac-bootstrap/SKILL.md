---
name: mac-bootstrap
description: Diagnose or explicitly prepare the Apple Silicon macOS development environment for this repository; do not use it to change application architecture or Windows behavior.
---

# macOS Bootstrap

Establish a reproducible macOS development baseline without conflating diagnosis with installation.

## Choose the operating mode

### Diagnosis

Use read-only checks to inspect:

- Mac architecture and macOS version
- Homebrew and installed formula visibility
- Python installations, selected interpreter, and active virtual environment
- `ffmpeg`, PortAudio, BlackHole, and visible audio devices
- symptoms consistent with missing microphone permission
- missing or incompatible prerequisites, especially on Apple Silicon

Do not install packages, change permissions, alter shell configuration, create audio devices, or mutate Python environments during diagnosis. Report observed state, missing items, and checks that could not run. Do not infer that a component works merely because a binary or directory exists.

### Installation or repair

Only enter this mode when the user explicitly requests environment changes. State the intended changes first, keep them staged and reversible, and verify each stage before continuing.

- Create or repair a project virtual environment only when explicitly requested.
- Install dependencies only when the task explicitly authorizes installation.
- Never blindly install the existing Windows-oriented requirements on macOS; assess compatibility and use a staged installation plan.
- Do not install or reconfigure BlackHole without explicit authorization.

Record environment findings, commands actually run, and unresolved prerequisites in the relevant project documentation. Never inspect or print secret values.
