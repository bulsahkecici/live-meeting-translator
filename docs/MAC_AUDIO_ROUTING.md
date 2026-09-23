# macOS Audio Routing Baseline

The Phase 2 diagnostic remains isolated from the translation pipeline. The
primary Mac application now uses two separate BlackHole devices so outgoing
translated speech and incoming conference subtitles cannot form a feedback
loop.

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

### Bidirectional application topology

```text
Outgoing to Zoom:
MacBook Pro Mikrofonu -> TR STT -> EN translation -> EN TTS
    -> BlackHole 2ch -> Zoom microphone

Incoming from Zoom:
Zoom speaker -> Zoom Incoming Monitor (Multi-Output)
    +-> MacBook Pro Hoparlörü (you hear the participant)
    +-> BlackHole 16ch -> EN STT -> TR translation -> GUI/overlay only
```

The verified baseline `Zoom Incoming Monitor` contains MacBook Pro Hoparlörü as
its primary device and BlackHole 16ch with drift correction. BlackHole 2ch is
deliberately excluded. That speaker-based layout is suitable for bounded route
diagnostics, but a real two-way meeting should replace the audible member with
wired headphones or a stable headset output. Otherwise remote speech can leak
into the MacBook microphone and enter the outgoing translation path. The
incoming pipeline has no playback or TTS stage.

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
Zoom speaker = Zoom Incoming Monitor
```

Re-check both selections inside every active meeting. Zoom can restore an
earlier or system-default device. A wrong speaker selection leaves the incoming
pipeline at zero submitted segments; a wrong microphone selection bypasses the
translated English output.

Never select BlackHole 2ch as the Zoom speaker: that sends the remote
participant back into Zoom's microphone path. Do not add BlackHole 2ch to the
Multi-Output device. Headphones are required for the next live acceptance
because the first real meeting showed acoustic pickup with the built-in speaker
route. The repository does not join meetings or transmit audio to another
person automatically.

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
