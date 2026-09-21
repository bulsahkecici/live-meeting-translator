#!/usr/bin/env bash

set -u

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
cd "$repo_root" || exit 1

failures=0

pass() {
    printf 'PASS: %s\n' "$1"
}

fail() {
    printf 'FAIL: %s\n' "$1"
    failures=$((failures + 1))
}

skip() {
    printf 'SKIP: %s\n' "$1"
}

printf '== Repository status ==\n'
if command -v git >/dev/null 2>&1; then
    git status --short
    pass "git status is available"
else
    skip "git is unavailable"
fi

printf '\n== Expected files ==\n'
while IFS= read -r expected_file; do
    [ -z "$expected_file" ] && continue
    if [ -f "$expected_file" ]; then
        pass "$expected_file exists"
    else
        fail "$expected_file is missing"
    fi
done <<'EOF'
README.md
requirements.txt
config.yaml.example
src/main.py
src/pipeline.py
src/audio_in.py
src/audio_out.py
src/devices.py
src/vad.py
src/stt_whisper.py
src/translate_deepl.py
src/tts_base.py
AGENTS.md
.codex/config.toml
docs/ARCHITECTURE.md
docs/MAC_V2_PLAN.md
docs/BENCHMARKS.md
EOF

printf '\n== Python syntax ==\n'
if command -v python3 >/dev/null 2>&1; then
    smoke_tmp="$(mktemp -d "${TMPDIR:-/tmp}/live-meeting-translator-smoke.XXXXXX")"
    trap 'rm -rf "$smoke_tmp"' EXIT
    if PYTHONPYCACHEPREFIX="$smoke_tmp/pycache" python3 -m compileall -q src; then
        pass "Python source compiles"
    else
        fail "Python source has a compile error"
    fi
else
    skip "python3 is unavailable; syntax and import checks were not run"
fi

printf '\n== Runtime imports ==\n'
if command -v python3 >/dev/null 2>&1; then
    missing_modules="$(python3 - <<'PY'
import importlib.util

modules = [
    "numpy", "sounddevice", "requests", "dotenv", "yaml", "cachetools",
    "faster_whisper", "webrtcvad", "edge_tts", "PyQt6",
]
print(" ".join(name for name in modules if importlib.util.find_spec(name) is None))
PY
)"
    if [ -n "$missing_modules" ]; then
        skip "application import not attempted; missing modules: $missing_modules"
    elif python3 -c 'import src.main'; then
        pass "src.main imports without initializing the pipeline"
    else
        fail "src.main import failed"
    fi
fi

printf '\n== Safe diff check ==\n'
if command -v git >/dev/null 2>&1; then
    if git diff --check; then
        pass "git diff --check"
    else
        fail "git diff --check"
    fi
else
    skip "git is unavailable; diff check was not run"
fi

printf '\n== Result ==\n'
if [ "$failures" -eq 0 ]; then
    pass "conservative smoke test completed"
    exit 0
fi

fail "conservative smoke test found $failures required check(s) failing"
exit 1
