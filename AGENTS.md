# Repository Engineering Policy

## Mission

This project provides near-real-time Turkish-to-English meeting translation:

`audio capture -> speech segmentation/VAD -> speech recognition -> translation -> speech synthesis -> virtual audio routing -> conferencing software`

The V2 target is Apple Silicon macOS while preserving a viable Windows path.

## Engineering rules

- Inspect the repository and trace the relevant execution path before editing.
- Prefer minimal, reviewable changes. Do not rewrite working modules merely to modernize style, and avoid giant multi-purpose refactors.
- Preserve Windows behavior unless a task explicitly retires it. Keep macOS-specific behavior out of the central pipeline and isolate platform-specific implementations behind interfaces or adapters.
- Evolve STT, translation, TTS, audio input, and audio output toward swappable backends.
- Never silently discard captured speech or clear important audio queues to make reported latency look lower. Audio continuity takes priority over artificially low latency.
- Treat real-time latency as a first-class metric. Measure before optimizing.
- Avoid unnecessary large model dependencies. A local LLM is optional and must have a measured purpose.
- Never expose secrets, alter `.env` without explicit instruction, or commit API keys.
- Do not commit generated audio, model files, logs, caches, or virtual environments.
- Add tests or deterministic validation whenever behavior changes.
- Update project planning documentation after meaningful implementation phases.
- Separate architecture changes from performance optimization when practical, and preserve a rollback path.

## Required workflow

For meaningful implementation tasks:

`inspect -> plan -> implement the smallest coherent change -> validate -> review -> update project docs`

End significant tasks with these headings:

- Changed
- Validated
- Not validated
- Known risks
- Next recommended task
