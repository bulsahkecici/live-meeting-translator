---
name: stt-migration
description: Evaluate or introduce Apple Silicon-optimized speech-to-text backends while retaining faster-whisper; do not use it for translation, TTS, or general pipeline rewrites.
---

# STT Migration

Introduce an Apple Silicon STT path incrementally and reversibly.

- Verify current technology, package support, repository constraints, and hardware before selecting a backend. MLX Whisper and whisper.cpp are candidates, not predetermined choices.
- Preserve the existing `faster-whisper` implementation initially.
- Add a stable STT abstraction before replacement when the current boundary is insufficient.
- Do not carry CUDA assumptions into the macOS backend.
- Keep Turkish support explicit and test representative short Turkish speech segments.
- Change only the STT slice; avoid translation and TTS changes during migration.
- Benchmark transcription quality and latency before choosing a default.

For every benchmark, record model name and size, backend/device, audio duration, processing time, real-time factor, language, and relevant decoding settings. Keep selection and fallback behavior explicit, retain a rollback path, and do not download models or install packages without task authorization.
