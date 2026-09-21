# Benchmarks

This document is a measurement template. STEP 0 establishes no performance baseline and contains no invented results.

## Measurement rules

- Record hardware, OS, Python version, configuration, and warm/cold state with each run.
- Use representative Turkish meeting speech and preserve the same samples across backend comparisons where permitted.
- Measure each stage independently and end to end with a monotonic clock.
- Report failures, queue overflow, and dropped or skipped audio; do not exclude them from results.
- Keep raw benchmark artifacts out of Git when they contain audio, transcripts, secrets, or generated media.

## STT

| Backend | Model | Hardware | Audio duration | Processing time | Real-time factor | Language | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| | | | | | | | |

## Translation

| Backend | Model/service | Input chars | Latency | Context size | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| | | | | | |

## TTS

| Backend | Model/voice | Text length | Time-to-first-audio | Total synthesis time | Audio duration | RTF | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| | | | | | | | |

## End-to-end

| Segment duration | STT | Translation | TTS first audio | TTS total | Playback start | End-to-end perceived latency | Dropped audio | Notes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| | | | | | | | | |

## Audio routing

These measurements cover only the raw Phase 2 microphone-to-BlackHole path. The
timestamp values are PortAudio callback scheduling latency, not translation or
human-perceived end-to-end latency.

| Date | Path | Format | Active duration | Queue high-water/final | Overflows | Underflows | Dropped chunks | Source RMS/peak | Loopback RMS/peak | Capture-to-playback timestamps | Notes |
| --- | --- | --- | ---: | --- | --- | --- | ---: | --- | --- | --- | --- |
| 2026-09-21 | MacBook Pro Mikrofonu -> BlackHole 2ch output -> BlackHole 2ch input | 48 kHz, float32, mono -> stereo, 480-frame blocks | 10.009 s | 6/0 blocks | input 0; loopback input 0; queue 0 | output 0; active queue 0 | 0 | 0.00371006/0.02991113 | 0.00367019/0.02991113 | mean 81.033 ms; min 81.023 ms; max 81.043 ms; n=1,007 | Raw bounded routing PASS; 483,360 captured/submitted frames; post-output loopback RMS/peak ratios 0.989252/1.000000; no recording, speakers, system-default changes, STT, translation, or TTS |
