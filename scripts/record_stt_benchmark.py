#!/usr/bin/env python3
"""Interactively record the local-only Turkish STT benchmark corpus."""
import argparse
import json
from pathlib import Path
import time
import wave

import numpy as np


def parse_device(value: str):
    """Preserve names while converting numeric device indexes to integers."""
    try:
        return int(value)
    except ValueError:
        return value


def parse_args():
    parser = argparse.ArgumentParser(
        description="Record prompted Turkish benchmark sentences locally."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/stt_manifest.json"),
    )
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument(
        "--device",
        type=parse_device,
        help="sounddevice input index or name",
    )
    return parser.parse_args()


def write_pcm16_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples.reshape(-1), -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("items", [])
    if not 8 <= len(items) <= 12:
        raise ValueError("STT recording manifest must contain 8-12 items")

    import sounddevice as sd

    print("Recordings stay local and are never uploaded.")
    print("Each exact sentence is shown before its microphone capture.")
    print("Press Enter for each recording, 's' to skip, or 'q' to stop.\n")

    for position, item in enumerate(items, start=1):
        relative_path = Path(item["audio_filename"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Unsafe audio path: {relative_path}")
        output_path = manifest_path.parent / relative_path
        duration = float(item.get("record_seconds", 7))

        print(f"[{position}/{len(items)}] {item['category']}")
        print(f"SAY EXACTLY: {item['reference_text']}")
        action = input("Press Enter to record, s to skip, or q to quit: ").strip().lower()
        if action == "q":
            break
        if action == "s":
            print("Skipped.\n")
            continue

        for remaining in (3, 2, 1):
            print(f"Recording starts in {remaining}...")
            time.sleep(1)
        print(f"RECORDING for {duration:.1f} seconds...")
        samples = sd.rec(
            int(duration * args.sample_rate),
            samplerate=args.sample_rate,
            channels=1,
            dtype="float32",
            device=args.device,
        )
        sd.wait()
        write_pcm16_wav(output_path, samples, args.sample_rate)
        print(f"Saved local recording: {output_path}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
