---
name: audio-routing
description: Diagnose and change real-time audio capture, playback, buffering, or virtual-device routing; do not use it for unrelated STT, translation, or TTS behavior.
---

# Audio Routing

Work on `sounddevice`, PortAudio/CoreAudio behavior, device enumeration and selection, sample rates, channel conversion, BlackHole, conferencing-app routing, buffering, underruns, overruns, feedback loops, and queue backpressure.

## Invariants

- Never silently drop user speech or clear captured audio to conceal backlog.
- Treat device indexes as transient across boots. Prefer stable identity/name matching and emit enough diagnostic information to explain selection.
- Measure queue depth, capture-to-playback latency, underruns, and overruns before tuning.
- Define backpressure behavior explicitly and preserve audio continuity wherever possible.
- Keep platform-specific routing behind an adapter or boundary rather than branching throughout the central pipeline.
- Do not change STT, translation, or TTS semantics while solving routing unless the routing fix truly requires it; document any such coupling.
- Check sample-rate and mono/stereo conversions at every device boundary.
- Prevent feedback by documenting the application output, conferencing input, monitoring output, and prohibited loop paths.

Validate with non-destructive device diagnostics first. Do not start live capture, alter system devices, or change permissions unless the task explicitly authorizes it.
