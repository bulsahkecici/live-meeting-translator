# Windows Installation Guide - Troubleshooting av Package

## The Problem

`faster-whisper==0.10.0` requires `av==11.*`, but pre-built wheels for `av` 11.x may not be available for Python 3.11 on Windows. This causes pip to try building from source, which requires Visual C++ Build Tools.

## Solutions

### Solution 1: Install Visual C++ Build Tools (Recommended)

This is the most reliable solution:

1. **Download:** [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. **Install:**
   - Run the installer
   - Select "C++ build tools" workload
   - Click Install
3. **Restart** your computer
4. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

### Solution 2: Try Installing av 11.x First

Sometimes a pre-built wheel is available:

```powershell
# Try to install av 11.x from pre-built wheel
pip install "av>=11.0,<12.0" --only-binary :all:

# If that works, install the rest
pip install -r requirements.txt
```

### Solution 3: Use a Different Python Version

Python 3.10 may have pre-built wheels for `av` 11.x:

```powershell
# Create venv with Python 3.10
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Solution 4: Manual Installation Order

Install packages in a specific order to handle conflicts:

```powershell
# 1. Install base dependencies (without faster-whisper)
pip install numpy==1.24.3 sounddevice==0.4.6 requests==2.31.0 python-dotenv==1.0.0 pyyaml==6.0.1 webrtcvad==2.0.10 cachetools==5.3.2

# 2. Try to install av 11.x
pip install "av>=11.0,<12.0" --only-binary :all:

# 3. If av installs, install faster-whisper
pip install faster-whisper==0.10.0
```

### Solution 5: Use Conda (Alternative)

Conda often has pre-built packages:

```powershell
# Install Miniconda/Anaconda first, then:
conda install -c conda-forge av
pip install faster-whisper==0.10.0 --no-deps
pip install -r requirements.txt --no-deps
pip install ctranslate2 huggingface-hub tokenizers onnxruntime
```

## Verification

After installation, verify everything works:

```powershell
python -c "import faster_whisper; print('faster-whisper OK')"
python -c "import av; print('av OK')"
python -m src.main --mode list-devices
```

## Current Status

If you see:
- `Successfully installed av-16.1.0` but then `ERROR: Failed building wheel for av`
- This means `faster-whisper` is trying to downgrade `av` to 11.x
- You need Visual C++ Build Tools to compile `av` 11.x from source

## Quick Fix Command

If you just installed Visual C++ Build Tools:

```powershell
# Remove existing av installation
pip uninstall av -y

# Install everything fresh
pip install -r requirements.txt
```
