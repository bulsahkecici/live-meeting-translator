---
name: translator-backend
description: Add, compare, or maintain interchangeable translation backends such as DeepL or an optional local service; do not use it for STT, TTS, or audio routing changes.
---

# Translator Backends

Maintain a stable translation boundary while preserving DeepL initially. Candidate future implementations include DeepL, a local LLM through an LM Studio/OpenAI-compatible endpoint, and an explicit hybrid strategy.

- Put translators behind a stable interface before changing the active backend.
- Do not send unnecessary transcript history to cloud services.
- Keep local-model prompts deterministic; live-mode output must contain translation only.
- Keep context deliberately small and measure translation latency separately from STT and TTS.
- Compare quality with representative technical Turkish, not synthetic English-only cases.
- Treat local LLM translation as optional, never mandatory merely because a model is available.
- Define timeout, retry, fallback, and failure visibility explicitly.
- Never log API keys or put keys in committed YAML or source files.

Document the backend, model/service, input size, context size, latency, quality observations, and fallback path. Do not install or start local models without explicit authorization.
