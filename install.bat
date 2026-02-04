@echo off
REM Installation helper script for zoom_live_translate
REM This script helps install dependencies, especially handling the av package issue

echo ========================================
echo Zoom Live Translate - Installation Helper
echo ========================================
echo.

REM Check if venv exists
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        echo Make sure Python 3.10+ is installed and in PATH
        pause
        exit /b 1
    )
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Upgrading pip, setuptools, wheel...
python -m pip install -U pip setuptools wheel

echo.
echo Attempting to install dependencies...
echo.

REM Try to install av from pre-built wheel first (if available)
echo Step 1: Installing faster-whisper dependencies...
echo.
echo Note: faster-whisper requires av==11.* which may need Visual C++ Build Tools
echo Trying to install av 11.x from pre-built wheel first...
echo.

REM Try to install av 11.0.0 from pre-built wheel (if available)
pip install "av>=11.0,<12.0" --only-binary :all: 2>nul
if errorlevel 1 (
    echo.
    echo WARNING: Could not install av 11.x from pre-built wheel.
    echo This package requires Visual C++ Build Tools to compile.
    echo.
    echo Please install Microsoft C++ Build Tools:
    echo https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo.
    echo After installing, restart your computer and run this script again.
    echo.
    echo Attempting to continue with other packages...
    echo.
) else (
    echo av 11.x installed successfully from pre-built wheel!
    echo.
)

echo Step 2: Installing PyTorch with CUDA support (for GPU acceleration)...
echo This is required for faster performance. It may download ~2.5GB.
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 (
    echo WARNING: Failed to install PyTorch with CUDA support.
    echo System will fall back to CPU mode.
) else (
    echo PyTorch with CUDA support installed successfully.
)
echo.

echo Step 3: Installing other dependencies...
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ========================================
    echo INSTALLATION FAILED
    echo ========================================
    echo.
    echo If you see errors about 'av' or 'Microsoft Visual C++':
    echo.
    echo 1. Install Microsoft C++ Build Tools:
    echo    https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo.
    echo 2. Restart your computer
    echo.
    echo 3. Run this script again
    echo.
    echo ========================================
    pause
    exit /b 1
) else (
    echo.
    echo ========================================
    echo INSTALLATION SUCCESSFUL!
    echo ========================================
    echo.
    echo Next steps:
    echo 1. Copy .env.example to .env and add your DeepL API key
    echo 2. Copy config.yaml.example to config.yaml and configure devices
    echo 3. Run: python -m src.main --mode list-devices
    echo.
)

pause
