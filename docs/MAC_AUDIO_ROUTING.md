# macOS Audio Routing Baseline

This Phase 2 diagnostic is isolated from the translation pipeline. It routes live
microphone frames in memory and neither records audio nor calls cloud services.

## Topology

```text
MacBook Pro Mikrofonu (1 channel, 48 kHz)
    -> sounddevice InputStream
    -> bounded queue (fail visibly; never evict speech)
    -> explicit mono-to-stereo copy
    -> sounddevice OutputStream
    -> BlackHole 2ch output
    -> BlackHole virtual loop
    -> BlackHole 2ch input (metrics only)
```

The BlackHole input observer never feeds the BlackHole output. MacBook speakers
are not opened, and the diagnostic does not change system defaults, create an
aggregate device, or enable monitoring.

## Safe usage

Activate the Phase 1 environment, list the current transient device indexes, and
then run the finite test by stable name:

```bash
source .venv/bin/activate
python scripts/test_blackhole_routing.py --list-devices
python scripts/test_blackhole_routing.py \
  --input-name "MacBook Pro Mikrofonu" \
  --output-name "BlackHole 2ch" \
  --duration 10
```

Device substrings must resolve uniquely. Exact matches take priority. The test
uses 48 kHz float32 audio in 480-frame blocks, explicitly copies mono input to
both BlackHole output channels, and observes the same BlackHole device's two
input channels. It exits nonzero for missing signal, callback starvation,
overflow, underflow, queue overflow, or a dropped captured block.
Loopback acceptance counts only frames observed after this diagnostic starts its
BlackHole output and checks that loopback RMS/peak remain consistent with the
submitted signal. Close other applications writing to BlackHole to avoid
confounding the raw traversal check.

## Verified baseline (2026-09-21)

The host-level test used `MacBook Pro Mikrofonu` (one input channel) and
`BlackHole 2ch` (two input and two output channels), both reported by Core Audio
at 48 kHz. A 10.009-second active run submitted every one of 483,360 captured
frames and observed 999 signal-bearing BlackHole-input blocks after output
started. Loopback/output RMS and peak ratios were 0.989252 and 1.000000.
Queue high-water/final depth was 6/0 blocks, and all overflow,
active-underflow, queue-overflow, and dropped-chunk counters were zero. See
`docs/MAC_V2_PLAN.md` and
`docs/BENCHMARKS.md` for the complete measured evidence.

## Conferencing setup

After the raw loopback diagnostic passes, configure Zoom manually:

```text
Zoom microphone = BlackHole 2ch
Zoom speaker = MacBook Pro Hoparlörü or headphones
```

Never select BlackHole as the Zoom speaker. That removes local playback and can
create confusing loop paths if monitoring is later added. Prefer headphones for
any future explicit monitoring test. This repository does not automate Zoom,
join meetings, or transmit audio to another person.

## Troubleshooting

- No microphone signal: speak during the bounded interval, confirm macOS
  microphone permission for the terminal/Codex host, and rerun device listing.
- Device not found or ambiguous: use a longer name substring. Do not save a
  numeric index; CoreAudio/PortAudio indexes can change after reboot.
- BlackHole input remains zero: close other tools that may own or alter the
  virtual route, confirm the selected BlackHole device has both input and output
  channels, then rerun the raw test before opening Zoom.
- Queue underflow/overflow: treat it as a failed continuity baseline. Do not hide
  it by clearing the queue. Independent device-clock drift is a later-phase
  concern and no resampling is introduced here.
- Feedback risk: never route BlackHole input back to BlackHole output, and never
  enable speaker monitoring automatically.
