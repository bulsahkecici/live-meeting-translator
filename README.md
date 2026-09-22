# Meeting Bridge — Turkish ⇄ English

A near-real-time meeting assistant for Apple Silicon macOS, with the existing
Windows path preserved. It sends your Turkish speech to conferencing software
as English audio and can display the remote participant's English speech as
Turkish subtitles.

## What It Does

The two audio directions are isolated:

- **You → meeting:** microphone → Turkish STT → DeepL TR→EN → English TTS →
  virtual microphone.
- **Meeting → you:** conference speaker route → English STT → DeepL EN→TR →
  GUI and optional always-on-top subtitle overlay. This path has no TTS or
  playback stage.

The primary Mac profile uses MLX Whisper for outgoing Turkish speech, Faster
Whisper for incoming English speech, Edge TTS, BlackHole 2ch, and BlackHole
16ch. Windows retains Faster Whisper, SAPI, VB-CABLE, and optional CUDA support.

## Prerequisites

### Apple Silicon macOS

- Apple Silicon Mac and Python 3.11
- PortAudio and ffmpeg
- BlackHole 2ch for outgoing translated audio
- BlackHole 16ch plus a `Zoom Incoming Monitor` Multi-Output device for incoming
  subtitles
- DeepL API key and internet access for translation and Edge TTS

### Windows 10/11

- Python 3.10 or 3.11
- VB-Audio Virtual Cable
- DeepL API key
- Visual C++ Build Tools when a required wheel is unavailable
- Headphones are strongly recommended

### Hardware guidance

- **16GB RAM** (for faster-whisper model)
- **Apple Silicon GPU/Metal** for the primary Mac STT path, or **4GB+ NVIDIA
  GPU** for optional Windows CUDA acceleration
- **Stable internet connection** (for DeepL API)

## Installation

### Apple Silicon macOS (primary development profile)

Use Python 3.11 and keep the macOS dependency layers separate from the
Windows-oriented `requirements.txt`:

```bash
brew install portaudio ffmpeg
brew install --cask blackhole-2ch blackhole-16ch
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements-macos-stt.txt
python -m pip install -r requirements-macos-app.txt
```

The checked-in `config.yaml` selects `MacBook Pro Mikrofonu`, BlackHole 2ch,
MLX Whisper large-v3-turbo, DeepL, and Edge TTS for Turkish-to-English audio.
It also captures Zoom's English output from a separate BlackHole 16ch device
and displays Turkish subtitles. Install PortAudio, ffmpeg, BlackHole 2ch, and
BlackHole 16ch separately, then create the `Zoom Incoming Monitor` Multi-Output
device described in `docs/MAC_AUDIO_ROUTING.md`. Put the DeepL key only in the
ignored local `.env` file; never commit or paste it into logs:

```text
DEEPL_API_KEY=your_actual_deepl_api_key_here
```

The remaining installation instructions describe the preserved Windows path.

For the primary Mac profile, set Zoom devices to:

```text
Microphone: BlackHole 2ch
Speaker: Zoom Incoming Monitor
```

The Multi-Output device lets you hear the remote participant through the
MacBook speakers while BlackHole 16ch provides the separate subtitle input.
Never use BlackHole 2ch as the Zoom speaker.

### Data handling

- Microphone and conference audio are processed locally by the selected STT
  backends and are not uploaded by this application.
- Only recognized text is sent to DeepL for translation.
- When Edge TTS is selected, translated text is sent to the Edge speech service
  to synthesize outgoing audio. Windows SAPI runs locally.
- Temporary synthesized audio is kept under `tmp/` and removed after playback.
- `.env`, logs, benchmark recordings/results, model files, caches, and virtual
  environments must remain untracked.

### Windows installation

#### 1. Install VB-Audio Virtual Cable

1. Download VB-CABLE from [vb-audio.com](https://vb-audio.com/Cable/)
2. Run the installer (requires admin privileges)
3. Restart your computer if prompted
4. Verify installation:
   - Open Windows Sound Settings
   - You should see "CABLE Input (VB-Audio Virtual Cable)" as a playback device
   - You should see "CABLE Output (VB-Audio Virtual Cable)" as a recording device

#### 2. Install Visual C++ Build Tools (when required)

The `av` package (dependency of faster-whisper) requires Visual C++ Build Tools on Windows.

**Option A: Install Build Tools (Recommended)**
1. Download [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. Run installer, select "C++ build tools" workload
3. Restart your computer after installation

**Option B: Use Installation Helper Script**
```powershell
# Run the installation helper script
.\install.bat
```

**Option C: Manual Installation**
```powershell
# Try installing av from a pre-built wheel first
pip install av --only-binary :all:
```

#### 3. Set Up Python Environment

```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Upgrade pip and install dependencies
python -m pip install -U pip setuptools wheel
pip install -r requirements.txt
```

**If `av` installation fails:**
- Install Visual C++ Build Tools (see above)
- Or try: `pip install av --only-binary :all:` to use pre-built wheel
- Or install manually: `pip install av` after installing build tools

#### 4. Configure the Application

1. **Copy configuration files:**
   ```powershell
   copy .env.example .env
   copy config.yaml.example config.yaml
   ```

2. **Edit `.env`:**
   ```
   DEEPL_API_KEY=your_actual_deepl_api_key_here
   ```

3. **Edit `config.yaml`:**
   - Set `audio.input.name_substring` to match your microphone (e.g., "USB Audio", "Microphone")
   - Verify `audio.output.name_substring` is "CABLE Input" (default)
   - Adjust other settings as needed (see config.yaml.example for details)

#### 5. Configure Zoom

1. Open Zoom Settings → Audio
2. **Microphone:** Select "CABLE Output (VB-Audio Virtual Cable)"
3. **Speaker:** Select your normal headset/speakers (NOT the cable)
4. **Important:** Use headphones/headset to prevent feedback loops

## Quick Start

Activate the environment first. On macOS:

```bash
source .venv/bin/activate
```

On Windows, activate `venv` as described above.

### 1. List Audio Devices

```bash
python -m src.main --mode list-devices
```

This shows all input/output devices with indices. Use this to find the correct device names/indices for your config.

### 2. Test Audio Routing

**Test beep (validates routing):**
```bash
python -m src.main --mode beep
```

Check Zoom's microphone meter - it should move when the beep plays.

**Test TTS:**
```bash
python -m src.main --mode test
```

This plays "This is a test of the translation system. One, two, three." through the virtual cable.

### 3. Run the bidirectional GUI

```bash
python -m src.main --mode gui
```

Press **OTURUMU BAŞLAT**. The left card shows your detected Turkish and the
English sent to the conference; the right card shows detected remote English
and its Turkish translation. The subtitle checkbox controls the always-on-top
overlay. Stopping the session drains accepted speech before workers exit.

For Zoom on the primary Mac profile, select:

```text
Microphone: BlackHole 2ch
Speaker: Zoom Incoming Monitor
```

### 4. Run outgoing translation without the GUI

```bash
python -m src.main --mode live
```

Or use the batch file:
```powershell
.\run.bat --mode live
```

**How to use:**
- Speak 1-2 sentences in Turkish
- Pause for 600ms+ (silence threshold)
- The system will process: STT → Translate → TTS → Output
- English audio will be sent to Zoom
- Turkish and English text will be printed to console (for manual fallback)

### 5. Dry Run Mode (Text Input)

Test translation without microphone:

```bash
python -m src.main --mode dryrun --text "Merhaba, nasılsınız?"
```

Or pipe text:
```bash
echo "Merhaba, nasılsınız?" | python -m src.main --mode dryrun
```

## Virtual Audio Cable Routing

### How It Works

```text
macOS outgoing:
MacBook microphone → TR STT → EN translation → EN TTS
    → BlackHole 2ch → Zoom microphone

macOS incoming:
Zoom speaker → Zoom Incoming Monitor
    ├─ MacBook speakers/headphones
    └─ BlackHole 16ch → EN STT → TR translation → subtitles

Windows outgoing:
Microphone → TR STT → EN translation → SAPI/Edge TTS
    → CABLE Input → CABLE Output → Zoom microphone
```

### Device Mapping

| Platform/path | Application device | Conference device |
| --- | --- | --- |
| macOS outgoing | output `BlackHole 2ch` | microphone `BlackHole 2ch` |
| macOS incoming | input `BlackHole 16ch` | speaker `Zoom Incoming Monitor` |
| Windows outgoing | output `CABLE Input` | microphone `CABLE Output` |

### Important Notes

- **Use headphones/headset** to prevent feedback loops
- On macOS, do **not** set the Zoom speaker to BlackHole 2ch or add BlackHole
  2ch to `Zoom Incoming Monitor`.
- On Windows, do **not** set the Zoom speaker to VB-CABLE.
- See [`docs/MAC_AUDIO_ROUTING.md`](docs/MAC_AUDIO_ROUTING.md) for the verified
  Mac topology and feedback-loop precautions.

## Configuration

### Audio Devices

Edit `config.yaml`:

```yaml
audio:
  input:
    name_substring: "USB Audio"  # Match your mic by name
    index_override: null          # Or use explicit index
  output:
    name_substring: "CABLE Input" # Virtual cable input
    index_override: null
```

### TTS Engine

Default is Windows SAPI (most reliable). To change:

```yaml
tts:
  engine: "sapi"  # sapi, edge, or clone
```

- **sapi**: Windows built-in (default, most stable)
- **edge**: Edge TTS (requires `edge-tts` and `ffmpeg` in PATH)
- **clone**: Voice cloning (not implemented, placeholder)

### STT Model

```yaml
stt:
  backend: "faster-whisper"
  model: "small"
  compute_type: "int8"
  device: "cpu"
```

For Apple Silicon, the checked-in primary profile uses:

```yaml
stt:
  backend: "mlx-whisper"
  model: "mlx-community/whisper-large-v3-turbo"
  language: "tr"
  beam_size: 1
```

MLX is macOS/Apple-Silicon-only and does not silently fall back. Faster Whisper
remains the cross-platform reference backend and supports CPU/CUDA settings.

### Incoming subtitles

`incoming_subtitles.enabled` controls the independent EN→TR subtitle channel.
The example configuration leaves it disabled for compatibility. The primary
Mac profile enables BlackHole 16ch capture and stereo-to-mono mixing. Always use
a different virtual device from the outgoing audio route.

### VAD Settings

```yaml
vad:
  silence_threshold_ms: 600    # End segment after this silence
  min_speech_duration_ms: 800  # Minimum speech to process
  max_segment_duration_ms: 8000 # Maximum segment length
```

## Troubleshooting

### Installation: Visual C++ Build Tools Required

**Problem:** `error: Microsoft Visual C++ 14.0 or greater is required` when installing `av`

**Root Cause:** `faster-whisper==0.10.0` requires `av==11.*`, but pre-built wheels for `av` 11.x may not exist for Python 3.11 on Windows, forcing a source build.

**Solutions:**
1. **Install Visual C++ Build Tools (Recommended):**
   - Download from [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
   - Run installer, select "C++ build tools" workload
   - Restart computer
   - Retry: `pip install -r requirements.txt`

2. **Try installing av 11.x first:**
   ```powershell
   pip install "av>=11.0,<12.0" --only-binary :all:
   pip install -r requirements.txt
   ```

3. **Use Python 3.10 instead:**
   ```powershell
   py -3.10 -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. **See detailed guide:** Check `INSTALL_WINDOWS.md` for more troubleshooting options.

### Device Not Found

**Problem:** "Could not find audio input/output device"

**Solutions:**
1. Run `python -m src.main --mode list-devices` to see available devices
2. Update `config.yaml` with correct `name_substring` or `index_override`
3. Ensure VB-CABLE is installed and shows up in device list

### No Audio in Zoom

**Problem:** Zoom microphone meter doesn't move

**Solutions:**
1. Verify Zoom microphone is set to "CABLE Output (VB-Audio Virtual Cable)"
2. Run `--mode beep` and check if meter moves
3. Check Windows Sound Settings → Recording → CABLE Output → Properties → Levels (should be > 0)
4. Ensure app is writing to "CABLE Input" (check logs)

On macOS, verify that Zoom's microphone is `BlackHole 2ch`, the application
output resolves to `BlackHole 2ch`, and the Zoom microphone meter moves during
`--mode beep` or `--mode test`.

### No incoming Turkish subtitles on macOS

1. Verify Zoom's speaker is `Zoom Incoming Monitor`.
2. Verify that the Multi-Output device contains MacBook speakers (primary) and
   BlackHole 16ch with drift correction, but does not contain BlackHole 2ch.
3. Run `python -m src.main --mode list-devices` and confirm BlackHole 16ch is
   available as an input.
4. Confirm `incoming_subtitles.enabled: true` and its input device is
   `BlackHole 16ch`.
5. Check the GUI session log and `logs/app.log` for capture, STT, or DeepL errors.

### Sample Rate Mismatch

**Problem:** Audio distortion or no audio

**Solutions:**
1. Default output is 48kHz (Zoom-friendly)
2. If issues persist, check device capabilities: `--mode list-devices`
3. Ensure config.yaml has correct sample rates:
   - Input: 16000Hz (for STT)
   - Output: 48000Hz (for Zoom)

### DeepL API Errors

**Problem:** "Translation failed" or "429 Rate Limited"

**Solutions:**
1. Check `.env` has correct `DEEPL_API_KEY`
2. Verify API key is valid (test at [DeepL API](https://www.deepl.com/docs-api))
3. Free tier has rate limits - wait and retry
4. Check internet connection
5. App will print Turkish text for manual translation on failure

### TTS Errors

**Problem:** "TTS failed" or no audio output

**Solutions:**
1. SAPI is default - should work on all Windows systems
2. Check logs in `logs/app.log` for details
3. English text is printed to console for manual use
4. Try `--mode test` to validate TTS independently

### Edge TTS Not Working

**Problem:** Edge TTS falls back to SAPI or gives "output_format not supported" warning

**Root Cause:** Your `edge-tts` package is outdated and doesn't support the `output_format` parameter needed for WAV output.

**Solution:** Upgrade edge-tts:
```powershell
python -m pip install -U edge-tts
```

**Verify upgrade worked:**
```powershell
python -c "import edge_tts,inspect; print('output_format' in inspect.signature(edge_tts.Communicate).parameters)"
```
Should print `True`. If it prints `False`, the package is still outdated.

### Feedback/Echo Loops

**Problem:** Audio feedback or echo

**Solutions:**
1. **Use headphones/headset** (most important)
2. Ensure Zoom speaker is NOT set to virtual cable
3. Lower microphone sensitivity in Windows Sound Settings
4. Mute Zoom speakers if using external speakers

### STT Not Working

**Problem:** No transcription or poor accuracy

**Solutions:**
1. Check microphone is working (test in Windows Sound Recorder)
2. Speak clearly and pause between sentences
3. Try larger STT model (e.g., "medium" instead of "small")
4. Check logs for STT errors
5. Ensure input device is correct in config

### High Latency

**Problem:** Long delay between speech and output

**Solutions:**
1. Use smaller STT model ("tiny" or "base")
2. Use GPU acceleration (`device: "cuda"` in config)
3. Reduce `max_segment_duration_ms` to process shorter segments
4. Check internet speed (affects DeepL API)

## Meeting Operating Procedure

### Before the Interview

1. **Test everything:**

   ```bash
   python -m src.main --mode list-devices
   python -m src.main --mode beep
   python -m src.main --mode test
   ```

2. **Check Zoom:**
   - macOS: Microphone = BlackHole 2ch; Speaker = Zoom Incoming Monitor
   - Windows: Microphone = CABLE Output; Speaker = Your headset (NOT cable)
   - Test microphone in Zoom settings

3. **Start the app:**
   ```bash
   python -m src.main --mode gui
   ```

### During the Interview

1. **Speak naturally:**
   - Speak 1-2 sentences in Turkish
   - Pause for 600ms+ (natural pause)
   - Wait for processing (watch console output)

2. **Monitor output:**
   - The left card shows your Turkish and outgoing English.
   - The right card and overlay show incoming English and Turkish subtitles.
   - Check Zoom microphone meter moves
   - Ask the remote participant to confirm the English audio

3. **If something fails:**
   - App prints English text to console
   - Copy/paste into Zoom chat as backup
   - App continues running (doesn't crash)

4. **Best practices:**
   - Speak clearly and at moderate pace
   - Pause between thoughts (helps VAD segmentation)
   - Keep sentences under 8 seconds
   - Monitor logs if issues occur

### After the Interview

- Press **OTURUMU DURDUR** and wait for accepted queues to drain
- Check `logs/app.log` for any errors
- Review both transcript cards for translation quality

## Architecture and backend boundaries

The synchronous compatibility path and the bounded live worker path use the same
backend contracts. `BackendFactory` lazily selects STT, translation, audio input,
and audio output implementations. TTS retains its existing engine interface.
Platform capability checks are isolated in `RuntimePlatform`.

- Outgoing live stages: STT → translation → TTS → blocking playback.
- Incoming live stages: English STT → Turkish translation → GUI signal.
- All stage queues are bounded and preserve FIFO order.
- Normal stop drains accepted speech; saturation fails visibly instead of
  clearing important queued audio.
- macOS-specific MLX and routing behavior remains behind backend/configuration
  boundaries, preserving the Windows Faster Whisper/SAPI/VB-CABLE path.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the complete runtime
flow and [`docs/MAC_V2_PLAN.md`](docs/MAC_V2_PLAN.md) for migration evidence.

## File Structure

```
zoom_live_translate/
├── README.md                 # This file
├── requirements.txt          # Preserved Windows dependencies
├── requirements-macos-stt.txt # Apple Silicon STT layer
├── requirements-macos-app.txt # macOS application/GUI layer
├── .env.example             # Environment variables template
├── config.yaml.example      # Configuration template
├── run.bat                  # Quick launcher
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── config.py            # Configuration management
│   ├── devices.py           # Audio device discovery
│   ├── audio_in.py          # Audio input capture
│   ├── audio_out.py         # Audio output streaming
│   ├── vad.py               # Voice Activity Detection
│   ├── stt_whisper.py       # Speech-to-Text (faster-whisper)
│   ├── stt_mlx.py           # Apple Silicon MLX Whisper backend
│   ├── translate_deepl.py   # Translation (DeepL API)
│   ├── tts_base.py          # TTS base interface
│   ├── tts_sapi.py          # Windows SAPI TTS
│   ├── tts_edge.py          # Edge TTS (optional)
│   ├── backend_factory.py   # Lazy backend selection
│   ├── pipeline.py          # Outgoing pipeline orchestration
│   ├── pipeline_runtime.py  # Bounded ordered live workers
│   ├── incoming_subtitles.py # Incoming subtitle-only pipeline
│   ├── ui/                  # Bidirectional GUI and overlay
│   └── utils.py             # Utility functions
├── docs/                    # Architecture, benchmarks, routing, plan
├── tests/                   # Deterministic regression suite
├── logs/                    # Created at runtime
│   └── app.log              # Application logs
└── tmp/                     # Created at runtime
    └── *.wav                # Temporary TTS output files
```

## Logging

Logs are written to `logs/app.log` with rotation (10MB max, 5 backups).

Log levels:
- **DEBUG**: Detailed diagnostic information
- **INFO**: General information (default)
- **WARNING**: Warning messages
- **ERROR**: Error messages

Change log level in `config.yaml`:
```yaml
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
```

## Error Handling

The app makes failures visible while preserving accepted audio:

- **Translation errors:** Prints Turkish + English (if any) to console, continues running
- **TTS errors:** Prints English text for manual copy/paste, continues running
- **STT errors:** Logs warning, skips segment, continues listening
- **Audio/backpressure errors:** Logs the failure and stops rather than silently
  deleting queued speech

The app **does not crash** on individual segment failures - it logs errors and continues processing.

## Performance

Performance depends on model load state, utterance length, network latency, TTS
audio duration, and the selected hardware backend. The repository records actual
model load time, inference time, RTF, WER/CER, and integration measurements in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md). Do not compare backends using
different audio or normalization.

On the verified primary Mac profile, outgoing live acceptance completed without
queue drops; its blocking playback dominated the measured 7.290-second segment.
The incoming local routing acceptance completed one English→Turkish subtitle
segment in 1.326 seconds after stereo mixing. These are bounded integration
checks, not sustained Zoom or thermal benchmarks.

## License

This project is provided as-is for personal use.

## Support

For issues:
1. Check `logs/app.log` for detailed error messages
2. Review troubleshooting section above
3. Verify all prerequisites are installed
4. Test each component individually (`--mode beep`, `--mode test`, etc.)

---

**Good luck with your interview!** 🎤🎯
