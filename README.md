# Zoom Live Translate

A Windows Python application that translates Turkish speech to English audio in real-time, routing the output to Zoom via a virtual audio cable. Designed for stability during long interviews (1+ hours).

## What It Does

1. **Captures** your Turkish speech from a microphone
2. **Detects** speech segments using Voice Activity Detection (VAD)
3. **Transcribes** Turkish speech to text using faster-whisper (local STT)
4. **Translates** text from Turkish to English using DeepL API
5. **Synthesizes** English text to speech using Windows SAPI TTS
6. **Outputs** English audio to a virtual audio cable that Zoom reads as your microphone

## Prerequisites

### Required

- **Windows 10/11**
- **Python 3.10+** (tested with 3.10, 3.11)
- **VB-Audio Virtual Cable** (VB-CABLE) - [Download here](https://vb-audio.com/Cable/)
- **DeepL API Key** - [Get free API key](https://www.deepl.com/pro-api)
- **Headset or headphones** (strongly recommended to prevent feedback loops)

### Recommended

- **16GB RAM** (for faster-whisper model)
- **4GB+ GPU** (optional, for CUDA acceleration)
- **Stable internet connection** (for DeepL API)

## Installation

### 1. Install VB-Audio Virtual Cable

1. Download VB-CABLE from [vb-audio.com](https://vb-audio.com/Cable/)
2. Run the installer (requires admin privileges)
3. Restart your computer if prompted
4. Verify installation:
   - Open Windows Sound Settings
   - You should see "CABLE Input (VB-Audio Virtual Cable)" as a playback device
   - You should see "CABLE Output (VB-Audio Virtual Cable)" as a recording device

### 2. Install Visual C++ Build Tools (Required)

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

### 3. Set Up Python Environment

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

### 4. Configure the Application

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

### 5. Configure Zoom

1. Open Zoom Settings → Audio
2. **Microphone:** Select "CABLE Output (VB-Audio Virtual Cable)"
3. **Speaker:** Select your normal headset/speakers (NOT the cable)
4. **Important:** Use headphones/headset to prevent feedback loops

## Quick Start

### 1. List Audio Devices

```powershell
python -m src.main --mode list-devices
```

This shows all input/output devices with indices. Use this to find the correct device names/indices for your config.

### 2. Test Audio Routing

**Test beep (validates routing):**
```powershell
python -m src.main --mode beep
```

Check Zoom's microphone meter - it should move when the beep plays.

**Test TTS:**
```powershell
python -m src.main --mode test
```

This plays "This is a test of the translation system. One, two, three." through the virtual cable.

### 3. Run Live Translation

```powershell
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

### 4. Dry Run Mode (Text Input)

Test translation without microphone:

```powershell
python -m src.main --mode dryrun --text "Merhaba, nasılsınız?"
```

Or pipe text:
```powershell
echo "Merhaba, nasılsınız?" | python -m src.main --mode dryrun
```

## Virtual Audio Cable Routing

### How It Works

```
Your Microphone → App captures audio
                ↓
         [STT + Translate + TTS]
                ↓
    CABLE Input (Playback Device)
                ↓
    Virtual Cable (internal routing)
                ↓
    CABLE Output (Recording Device)
                ↓
         Zoom Microphone Input
```

### Device Mapping

| Component | Device Name |
|-----------|-------------|
| **App writes to** | `CABLE Input (VB-Audio Virtual Cable)` |
| **Zoom reads from** | `CABLE Output (VB-Audio Virtual Cable)` |
| **Your speakers** | Your normal headset/speakers (NOT the cable) |

### Important Notes

- **Use headphones/headset** to prevent feedback loops
- **Do NOT** set Zoom speaker to the virtual cable
- The virtual cable is a **one-way** audio path: App → Cable → Zoom

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
  model: "small"  # tiny, base, small, medium, large
  compute_type: "int8"  # int8, float16, float32
  device: "cpu"  # cpu or cuda
```

- Smaller models = faster, less accurate
- Larger models = slower, more accurate
- `int8` = faster, lower quality
- `cuda` = GPU acceleration (if available)

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

## Interview Operating Procedure

### Before the Interview

1. **Test everything:**
   ```powershell
   python -m src.main --mode beep      # Verify routing
   python -m src.main --mode test      # Verify TTS
   ```

2. **Check Zoom:**
   - Microphone = CABLE Output
   - Speaker = Your headset (NOT cable)
   - Test microphone in Zoom settings

3. **Start the app:**
   ```powershell
   python -m src.main --mode live
   ```

### During the Interview

1. **Speak naturally:**
   - Speak 1-2 sentences in Turkish
   - Pause for 600ms+ (natural pause)
   - Wait for processing (watch console output)

2. **Monitor output:**
   - Console shows: `[TURKISH] ...` and `[ENGLISH] ...`
   - Check Zoom microphone meter moves
   - Listen for English audio in Zoom

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

- Press `Ctrl+C` to stop the app
- Check `logs/app.log` for any errors
- Review console output for translation quality

## Architecture: Pluggable TTS

The code is designed for easy TTS engine swapping. To add voice cloning later:

1. **Implement `CloneTTSEngine`** inheriting from `TTSEngine`:
   ```python
   class CloneTTSEngine(TTSEngine):
       def synthesize_to_wav(self, text, wav_path, sample_rate):
           # Your voice cloning implementation
           pass
   ```

2. **Update `pipeline.py`** to instantiate your engine:
   ```python
   elif engine_name == 'clone':
       self.tts = CloneTTSEngine(...)
   ```

3. **Set config:**
   ```yaml
   tts:
     engine: "clone"
   ```

The interface is defined in `src/tts_base.py` - all TTS engines must implement:
- `synthesize_to_wav(text, wav_path, sample_rate)` → bool
- `is_available()` → bool

## File Structure

```
zoom_live_translate/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
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
│   ├── translate_deepl.py   # Translation (DeepL API)
│   ├── tts_base.py          # TTS base interface
│   ├── tts_sapi.py          # Windows SAPI TTS
│   ├── tts_edge.py          # Edge TTS (optional)
│   ├── tts_clone_stub.py    # Voice cloning stub
│   ├── pipeline.py          # Main pipeline orchestration
│   └── utils.py             # Utility functions
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

The app is designed to be resilient:

- **Translation errors:** Prints Turkish + English (if any) to console, continues running
- **TTS errors:** Prints English text for manual copy/paste, continues running
- **STT errors:** Logs warning, skips segment, continues listening
- **Audio errors:** Logs error, attempts to recover

The app **does not crash** on individual segment failures - it logs errors and continues processing.

## Performance

Typical latency per segment:
- **STT:** 1-3 seconds (depends on model and hardware)
- **Translation:** 0.5-2 seconds (depends on API and internet)
- **TTS:** 0.5-1.5 seconds (depends on text length)
- **Total:** 2-6 seconds per segment

For best performance:
- Use GPU acceleration for STT (`device: "cuda"`)
- Use smaller STT model ("tiny" or "base")
- Ensure stable internet connection
- Keep segments short (speak 1-2 sentences, pause)

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

