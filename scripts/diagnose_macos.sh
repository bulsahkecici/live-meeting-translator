#!/usr/bin/env bash

set -u

section() {
    printf '\n== %s ==\n' "$1"
}

found() {
    printf 'FOUND: %s\n' "$1"
}

missing() {
    printf 'MISSING: %s\n' "$1"
}

info() {
    printf 'INFO: %s\n' "$1"
}

section "System"
if command -v uname >/dev/null 2>&1; then
    found "uname ($(command -v uname))"
    uname -m || info "uname could not report architecture"
else
    missing "uname"
fi

if command -v sw_vers >/dev/null 2>&1; then
    found "sw_vers ($(command -v sw_vers))"
    sw_vers || info "sw_vers could not report macOS version"
else
    missing "sw_vers (this may not be macOS)"
fi

section "Development tools"
if command -v brew >/dev/null 2>&1; then
    found "Homebrew ($(command -v brew))"
    brew --version | sed -n '1p' || info "Homebrew version check failed"
else
    missing "Homebrew"
fi

if command -v python3 >/dev/null 2>&1; then
    found "python3 ($(command -v python3))"
    python3 --version || info "python3 version check failed"
    which python3 || info "which could not resolve python3"
else
    missing "python3"
fi

if [ -n "${VIRTUAL_ENV:-}" ]; then
    found "active Python virtual environment: ${VIRTUAL_ENV}"
else
    missing "active Python virtual environment"
fi

if command -v git >/dev/null 2>&1; then
    found "git ($(command -v git))"
    git --version || info "git version check failed"
else
    missing "git"
fi

section "Media and audio prerequisites"
if command -v ffmpeg >/dev/null 2>&1; then
    found "ffmpeg ($(command -v ffmpeg))"
    ffmpeg -version 2>/dev/null | sed -n '1p' || info "ffmpeg version check failed"
else
    missing "ffmpeg"
fi

if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists portaudio-2.0 2>/dev/null; then
    found "PortAudio via pkg-config"
    info "PortAudio version: $(pkg-config --modversion portaudio-2.0 2>/dev/null)"
elif command -v brew >/dev/null 2>&1 && brew list --versions portaudio >/dev/null 2>&1; then
    found "PortAudio via Homebrew"
    brew list --versions portaudio || info "Homebrew could not report PortAudio version"
else
    missing "detectable PortAudio installation"
fi

blackhole_found=0
for audio_plugin_root in /Library/Audio/Plug-Ins/HAL "${HOME:-}/Library/Audio/Plug-Ins/HAL"; do
    if [ -d "$audio_plugin_root" ] && find "$audio_plugin_root" -maxdepth 1 -iname 'BlackHole*.driver' -print -quit 2>/dev/null | grep -q .; then
        found "BlackHole driver under $audio_plugin_root"
        blackhole_found=1
    fi
done
if [ "$blackhole_found" -eq 0 ]; then
    missing "BlackHole driver in standard HAL plugin directories"
fi

if command -v system_profiler >/dev/null 2>&1; then
    info "CoreAudio-visible devices reported by system_profiler follow"
    if ! system_profiler SPAudioDataType 2>/dev/null; then
        info "system_profiler audio query failed"
    fi
else
    missing "system_profiler; audio devices were not enumerated"
fi

info "Microphone permission cannot be proven by this read-only script. A missing or silent input device during a later authorized capture test may indicate that permission is absent."

section "Result"
info "Diagnosis only: no packages, devices, permissions, shell settings, or Python environments were changed."
