# macOS V2 Migration Plan

Statuses use `COMPLETE` or `PENDING`. Repository scaffolding and the macOS environment/bootstrap baseline are complete; no later-phase runtime technology is claimed installed or working.

## PHASE 0 — Codex/repository development scaffolding

**Objective:** Establish durable repository policy, focused skills and agents, architecture/planning records, benchmark templates, and safe diagnostics.

**Prerequisites:** Existing repository available for read-only inspection.

**Tasks:** Inspect the current implementation and platform assumptions; add `AGENTS.md`; add repository-local skills and read-only agents; enable conservative multi-agent configuration; document current architecture and the migration plan; add benchmark templates and non-invasive scripts.

**Acceptance criteria:** Requested files exist and parse; scripts run without installation or runtime calls; syntax/frontmatter/TOML and Git diff checks pass; no protected application or configuration file changes.

**Risks:** Documentation may become stale unless later phases update it; custom skills and agents may require a new Codex session before discovery.

**Status:** COMPLETE (STEP 0)

## PHASE 1 — macOS environment/bootstrap

**Objective:** Establish a supported Apple Silicon Python and native-tool baseline without changing application behavior.

**Prerequisites:** Phase 0; explicit authorization before installing or altering dependencies.

**Tasks:** Run `$mac-bootstrap` in diagnosis mode; choose a compatible Python version; assess Homebrew, PortAudio, ffmpeg, and current package compatibility; create a staged environment plan; install only after approval; record exact versions and gaps.

**Acceptance criteria:** A reproducible environment report exists; the chosen interpreter and virtual environment are documented; approved foundational imports pass; no Windows environment files are overwritten.

**Risks:** Python 3.14 wheel availability, native build failures, conflicting package pins, and accidental use of the Windows freeze file.

**Status:** COMPLETE

### Phase 1 environment record (2026-09-21)

- Platform: macOS 26.6.2 on native `arm64` Apple Silicon.
- Homebrew: operational at `/opt/homebrew/bin/brew`; version 7.0.4 after the normal auto-update performed during installation.
- Python: Homebrew `python@3.11` 3.11.16 installed alongside the unchanged `python@3.14` 3.14.6. The project environment is `.venv`, created explicitly with `/opt/homebrew/opt/python@3.11/bin/python3.11`; `.venv/bin/python` reports Python 3.11.16 and `arm64`.
- Packaging tools and requested direct diagnostic packages: `pip` 26.2.1, `setuptools` 84.0.0, `wheel` 0.48.0, `numpy` 2.4.6, and `sounddevice` 0.5.6. Expected transitive packages are `packaging` 26.3, `cffi` 2.1.1, and `pycparser` 3.0. The Windows-oriented `requirements.txt` was not installed or modified.
- Native tools: ffmpeg 9.0.2 and PortAudio 19.7.0 are installed through Homebrew.
- BlackHole: the user completed the standard installer and restarted macOS. Three independent layers were verified: the Installer receipt `audio.existential.BlackHole2ch` reports version 0.7.1 at `Library/Audio/Plug-Ins/HAL`; `/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver` is present with bundle version 0.7.1; and both `system_profiler SPAudioDataType` and PortAudio through `sounddevice` see `BlackHole 2ch` as a two-input/two-output Core Audio device at a current/default sample rate of 48 kHz. The manual Installer receipt is the installation evidence; `brew list --cask --versions blackhole-2ch` did not report a Homebrew-managed cask installation.
- CoreAudio enumeration: the repository's host-level `python -m src.devices` check sees `BlackHole 2ch` as a two-input/two-output 48 kHz Core Audio device, `MacBook Pro Mikrofonu` as a one-input-channel 48 kHz Core Audio device, and `MacBook Pro Hoparlörü` as a two-output-channel 48 kHz Core Audio device. PortAudio reported the built-in microphone and speakers as the current defaults. Device indexes were observed only for diagnosis and are not stored in application configuration. Restricted-shell enumeration still cannot see CoreAudio devices, so host-level enumeration is required for meaningful audio diagnostics.
- Audio baseline: PortAudio settings validation accepted 16, 44.1, 48, and 96 kHz for the named built-in microphone input and BlackHole output. This indicates configurations accepted through the Core Audio/PortAudio path, not distinct native hardware rates; the reported current/default rate for all three relevant devices is 48 kHz. A named built-in-microphone stream opened and started at 48 kHz. The first bounded 100 ms read returned 4,800 finite but zero-valued frames without overflow; an independent bounded 100 ms review capture then returned 4,800 finite, non-zero samples without overflow (peak approximately 0.01127 and RMS approximately 0.00114), verifying actual capture and superseding the initially inconclusive silent buffer. A named BlackHole stereo output stream opened at 48 kHz, and a bounded 100 ms memory-only silent write completed without underflow. No audio was saved or retained. No system defaults, aggregate devices, conferencing settings, `config.yaml`, or application source were changed.
- Microphone permission: verified separately through the public AVFoundation `AVCaptureDevice.authorizationStatus(for: .audio)` API, which returned `authorized`; no TCC database was read or modified. Device visibility, authorization, stream open/start, frame delivery, and non-zero capture were all observed through normal APIs.
- Commands run for the environment stage included `brew install python@3.11`, explicit `python3.11 -m venv .venv`, `.venv/bin/python -m pip install --upgrade pip setuptools wheel`, `brew install ffmpeg portaudio`, `.venv/bin/python -m pip install numpy sounddevice`, `python -m src.devices`, `./scripts/diagnose_macos.sh`, and `./scripts/smoke_test.sh`. The non-interactive `brew install --cask blackhole-2ch` attempt stopped at its normal administrator-password requirement.

The final Phase 1 continuation reran `python -m src.devices`, `./scripts/diagnose_macos.sh`, and `./scripts/smoke_test.sh` with the existing `.venv` activated. The diagnostics found the expected native tools, HAL driver, and CoreAudio devices; source compilation and `git diff --check` passed. The smoke test conservatively skipped the full application import because intentionally uninstalled later-phase/runtime packages remain absent. Phase 1 is complete: the staged Apple Silicon environment, virtual environment, foundational audio import, BlackHole installation/visibility, and bounded stream checks are verified without changing application behavior or Windows files.

## PHASE 2 — macOS audio routing baseline

**Objective:** Prove reliable microphone capture and virtual output routing on macOS before altering higher pipeline stages.

**Prerequisites:** Phase 1; explicit authorization for BlackHole installation or system audio changes.

**Tasks:** Enumerate CoreAudio devices; validate supported rates and channels; define stable device selection; design BlackHole/conferencing routing; test non-live diagnostics before capture/playback; document feedback prevention and permission symptoms.

**Acceptance criteria:** Repeatable capture and output-device checks pass on named hardware; raw BlackHole input loopback proves signal traversal; conferencing routing is documented and reported separately as PASS, FAIL, or NOT RUN; underrun/overrun and feedback observations are recorded; no speech semantics change.

**Risks:** Device reordering, microphone permissions, aggregate-device drift, sample-rate mismatch, Bluetooth mode changes, and feedback loops.

**Status:** COMPLETE (raw BlackHole routing baseline; conferencing validation NOT RUN)

### Phase 2 diagnostic

- `scripts/test_blackhole_routing.py` is a production-isolated, finite diagnostic for the named microphone -> bounded memory queue -> explicit mono-to-stereo conversion -> named BlackHole output path. It simultaneously observes the exact same BlackHole device's input side without routing that input anywhere.
- Device selection uses a unique case-insensitive name match, prefers an exact name, and fails on ambiguous substrings. Reported numeric indexes are diagnostic only and are never persisted.
- The initial format is fixed at the Phase 1 common rate of 48 kHz with 480-frame blocks. The queue holds at most 50 blocks and begins output after a six-block prefill. A full queue preserves already queued speech, records the current block as dropped, and fails the run visibly; it never evicts old speech.
- Metrics cover source/output/loopback callbacks and frames, source/submitted/loopback RMS, peak, and signal-bearing blocks, post-output-start loopback/output signal-level consistency, queue high-water/final depth, capture-to-playback scheduling latency when PortAudio supplies valid timestamps, PortAudio input/output status flags, queue starvation/overflow, and dropped chunks. Audio samples are never written or retained.
- Safe topology, Zoom's required manual microphone/speaker settings, feedback prevention, and troubleshooting are documented in `docs/MAC_AUDIO_ROUTING.md`.
- Pure-logic tests cover exact/substring/ambiguous device matching, explicit mono-to-stereo conversion, queue saturation behavior, streaming signal metrics, and configuration validation. Hardware-dependent results remain integration evidence and must not be inferred from unit tests.

### Phase 2 evidence (2026-09-21)

- Host-level CoreAudio enumeration resolved `MacBook Pro Mikrofonu` as a one-input/zero-output, 48 kHz Core Audio device and `BlackHole 2ch` as a two-input/two-output, 48 kHz Core Audio device. The observed indexes were 1 and 0 respectively, but are not stored and are not assumed stable.
- A bounded 10-second run used 48 kHz float32 audio, 480-frame blocks, a 50-block queue, and a six-block prefill. It explicitly duplicated the microphone's mono samples into both BlackHole output channels. The BlackHole input stream only observed signal and was never fed back into an output or speaker.
- The final hardened run measured 10.009 seconds of active routing, 1,007 microphone callbacks/483,360 source frames, 1,014 output callbacks/483,360 submitted frames, and 1,039 BlackHole-input callbacks/493,920 post-output-start observed frames. Source RMS/peak were 0.00371006/0.02991113; submitted BlackHole-output RMS/peak were identical; BlackHole-input RMS/peak were 0.00367019/0.02991113. Source, submitted-output, and post-output-start loopback each contained 999 signal-bearing blocks. The loopback/output RMS ratio was 0.989252 and peak ratio was 1.000000.
- PortAudio callback timestamps produced 1,007 capture-to-playback scheduling observations: mean 81.033 ms, minimum 81.023 ms, and maximum 81.043 ms. These are measured callback scheduling timestamps, not end-to-end translation latency.
- Queue high-water mark was six blocks and final depth was zero. Microphone input overflows, BlackHole input overflows, output underflows, active queue underflows, queue overflows, and dropped chunks were all zero. Captured and submitted frame counts matched exactly.
- The first hardware run exposed one terminal callback incorrectly classified as active queue starvation while the microphone stream was stopping. Every captured block had still been submitted and the queue had drained. The diagnostic lifecycle was corrected to distinguish the bounded shutdown transition from active-run starvation; deterministic tests passed again before the successful hardware rerun.
- System defaults were not changed; no aggregate or multi-output device was created; speakers were not opened; no microphone samples were written or retained; and production application/configuration files were not modified.
- Zoom/conferencing validation was not run. Required manual settings remain `Zoom microphone = BlackHole 2ch` and `Zoom speaker = MacBook Pro Hoparlörü or headphones` (never BlackHole), as documented in `docs/MAC_AUDIO_ROUTING.md`.

## PHASE 3 — backend abstractions

**Objective:** Isolate platform and provider implementations without changing the selected runtime behavior.

**Prerequisites:** Phases 1–2; current-path characterization tests.

**Tasks:** Define minimal interfaces for STT, translator, audio input, and audio output; retain the current TTS interface; add factories/config selection at one boundary; wrap existing implementations first; add contract-focused tests.

**Acceptance criteria:** Existing Windows backends remain selectable; current CLI modes retain behavior; central orchestration does not import platform-only implementations directly; rollback is straightforward.

**Risks:** Over-generalized interfaces, constructor side effects, configuration drift, and accidental fallback changes.

**Status:** COMPLETE

### Phase 3 implementation record (2026-09-21)

**IMPLEMENTED NOW:** `backend_interfaces.py` defines ABC contracts for the exact STT, translator, audio-input, and audio-output operations consumed by the pipeline. Existing `STTWhisper`, `DeepLTranslator`, `AudioInput`, and `AudioOutput` implement those contracts, while the existing `TTSEngine` ABC remains the single TTS abstraction. `backend_factory.py` maps configuration to the existing faster-whisper, DeepL, SAPI, Edge, clone-stub, sounddevice, and VAD implementations through function-local imports. `PipelineComponents` provides complete constructor injection, and normal `TranslationPipeline(config)` startup still builds the same components automatically in the legacy order.

Existing configuration remains compatible when `stt.backend` and `translate.backend` are absent; their internal defaults are `faster-whisper` and `deepl`. Existing audio sample-rate and VAD compatibility keys remain accepted, and `tts.engine` keeps its existing values. `config.yaml` was not changed. The example documents only currently implemented selectors.

`runtime_platform.py` now exposes deterministic OS, Apple Silicon, SAPI, CUDA-relevance, and virtual-routing facts without overriding configured device names. Windows keeps the existing unavailable-TTS-to-SAPI fallback. Non-Windows startup now rejects explicit SAPI selection or an unavailable engine's invalid SAPI fallback with a clear error.

Import boundaries are lighter: `TranslationPipeline` no longer imports concrete AI/TTS backends, factory imports are lazy, and `src.main` handles device listing before importing configuration or pipeline modules. Deterministic tests use injected fakes and patched constructors; they do not access microphones, virtual devices, networks, model downloads, CUDA, MLX, Edge service, or SAPI.

The serial stage order, blocking playback, `run_live()` loop, queue overflow policy, and both existing queue-clearing behaviors are unchanged. Phase 3 does not address captured-speech loss or concurrency.

**FUTURE BACKENDS — NOT IMPLEMENTED:** MLX Whisper, local/hybrid LLM translation, and local/streaming TTS remain later-phase candidates. No new AI dependency or model was added.

## PHASE 4 — Apple Silicon STT

**Objective:** Add and evaluate an Apple Silicon-optimized Turkish STT backend while preserving faster-whisper.

**Prerequisites:** Phases 1 and 3; representative, permitted Turkish audio samples; benchmark protocol.

**Tasks:** Verify current MLX Whisper and whisper.cpp options; select a candidate based on compatibility; implement behind the STT interface; benchmark warm/cold latency, RTF, memory, and transcription quality; define fallback.

**Acceptance criteria:** Existing faster-whisper remains usable; the candidate passes Turkish samples; benchmark rows identify model/backend/hardware; selection is configuration-driven and reversible.

**Risks:** Model download size, unsupported Python version, backend API churn, Metal memory pressure, and quality regression.

**Status:** PENDING

## PHASE 5 — pipeline concurrency

**Objective:** Replace serial stage execution incrementally with bounded queues and workers while preserving ordered, continuous audio.

**Prerequisites:** Phase 3; stage timing and queue behavior tests; agreed overload policy.

**Tasks:** Add structured stage messages and latency IDs; introduce one bounded queue at a time; add STT, translation, TTS, then playback workers; specify backpressure; remove queue-clearing only after continuity tests; implement clean drain/shutdown and failure propagation.

**Acceptance criteria:** Ordered output survives concurrent operation; saturation does not silently delete speech; shutdown cannot deadlock; queue depth and per-stage latency are observable; each subphase can be rolled back.

**Risks:** Races, deadlocks, unbounded latency, out-of-order output, unsafe callbacks, and memory growth.

**Status:** PENDING

## PHASE 6 — local/streaming TTS

**Objective:** Add a macOS-capable low-latency TTS option without removing SAPI or Edge TTS prematurely.

**Prerequisites:** Phases 1, 3, and preferably 5; voice/licensing review; TTS benchmarks.

**Tasks:** Evaluate current local and streaming candidates; measure time-to-first-audio and total synthesis; implement the chosen backend behind `TTSEngine`; support chunk-safe playback if streaming is justified; define failure fallback.

**Acceptance criteria:** English output is intelligible and correctly formatted for the output path; first-audio and total-time results are recorded; Windows SAPI remains available; fallback is explicit.

**Risks:** Large models, licensing restrictions, voice quality, stream gaps, format mismatch, and output ordering.

**Status:** PENDING

## PHASE 7 — local/hybrid translation

**Objective:** Evaluate optional local or hybrid translation against DeepL for latency, privacy, and technical Turkish quality.

**Prerequisites:** Phase 3; representative evaluation set; approved local service/model if tested.

**Tasks:** Preserve DeepL; add a translator interface implementation for an approved OpenAI-compatible local endpoint if justified; design deterministic translation-only prompts; cap context; benchmark latency and quality; define hybrid and failure policy.

**Acceptance criteria:** DeepL remains selectable; no keys enter committed YAML/logs; local output contains translation only in live mode; comparison data supports any default change.

**Risks:** Hallucination, extra commentary, long context latency, local service unavailability, and hidden cloud fallback.

**Status:** PENDING

## PHASE 8 — GUI/observability

**Objective:** Make state, latency, backlog, errors, and selected devices visible without parsing log strings.

**Prerequisites:** Phases 3 and 5; stable structured pipeline events.

**Tasks:** Replace log-text coupling with structured signals; display backend/device state, queue depth, stage timings, and recoverable errors; keep the GUI responsive; preserve CLI diagnostics and platform-neutral presentation.

**Acceptance criteria:** UI state follows structured events; long operations do not freeze the event loop; operational errors are actionable; logs contain no secrets.

**Risks:** thread-affinity violations, excessive metrics overhead, noisy UI, and GUI/CLI behavior divergence.

**Status:** PENDING

## PHASE 9 — benchmarking/hardening

**Objective:** Demonstrate sustained correctness, continuity, and acceptable latency on both supported platforms.

**Prerequisites:** Candidate V2 path complete; benchmark corpus and acceptance thresholds agreed.

**Tasks:** Run long-duration and overload tests; benchmark each stage and end to end; test device loss, network failure, queue saturation, cancellation, and recovery; inspect resource growth; run Windows regression checks.

**Acceptance criteria:** Results populate `docs/BENCHMARKS.md`; no unexplained dropped speech occurs; shutdown/recovery tests pass; known limitations are documented; Windows regression status is explicit.

**Risks:** hardware-dependent results, intermittent device behavior, thermal throttling, network variance, and insufficient Windows test access.

**Status:** PENDING

## PHASE 10 — packaging/release

**Objective:** Produce reproducible macOS distribution and release guidance while retaining a supportable Windows path.

**Prerequisites:** Phase 9 acceptance criteria; dependency and licensing inventory; release/version policy.

**Tasks:** Select packaging approach; define configuration and first-run diagnostics; handle model assets deliberately; assess signing/notarization and permissions; write platform-specific install/run/rollback documentation; build release artifacts in CI where practical.

**Acceptance criteria:** A clean machine can follow documented setup; artifacts are versioned and validated; secrets and local paths are absent; licenses and large assets are handled correctly; rollback instructions work.

**Risks:** signing/notarization complexity, binary size, native-library bundling, model licensing, and divergent platform installers.

**Status:** PENDING

## Architecture Decision Log

These are candidates for later evidence-based decisions, not accepted ADRs.

| ID | Candidate decision | Status | Evidence needed |
| --- | --- | --- | --- |
| ADR-CANDIDATE-001 | Preserve Windows backends while adding macOS implementations. | Candidate | Interface design and Windows regression coverage |
| ADR-CANDIDATE-002 | Introduce backend interfaces before replacing STT. | Candidate | Current coupling map and contract tests |
| ADR-CANDIDATE-003 | Avoid a synchronous monolithic pipeline in V2. | Candidate | Stage timing, queue-depth, and continuity measurements |
| ADR-CANDIDATE-004 | Prefer stable audio device identity/name matching over stored indexes. | Candidate | CoreAudio and Windows device-enumeration trials |
| ADR-CANDIDATE-005 | Select Apple Silicon STT only after Turkish quality/latency comparison. | Candidate | Reproducible MLX/whisper.cpp/faster-whisper benchmarks |
| ADR-CANDIDATE-006 | Keep local LLM translation optional with explicit fallback. | Candidate | Quality, latency, privacy, and resource measurements |
