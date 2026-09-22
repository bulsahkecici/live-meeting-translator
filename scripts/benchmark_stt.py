#!/usr/bin/env python3
"""Benchmark one STT backend/model in a fresh process."""
import argparse
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import wave

import numpy as np

try:
    import resource
except ImportError:  # Windows does not provide the Unix resource module.
    resource = None

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.stt_metrics import character_error_counts, word_error_counts


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark a single STT backend/model on one manifest."
    )
    parser.add_argument(
        "--backend",
        required=True,
        choices=("faster-whisper", "mlx-whisper"),
    )
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/stt_manifest.json"),
    )
    parser.add_argument("--language", default="tr")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Download/load the model without running timed inference.",
    )
    return parser.parse_args()


def load_manifest(manifest_path: Path):
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("items")
    if not isinstance(items, list) or not 8 <= len(items) <= 12:
        raise ValueError("STT benchmark manifest must contain 8-12 items")

    resolved_items = []
    for item in items:
        for key in ("id", "reference_text", "category", "audio_filename"):
            if not item.get(key):
                raise ValueError(f"Manifest item is missing {key!r}")
        relative_path = Path(item["audio_filename"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(
                f"Manifest audio path must be repository-relative: {relative_path}"
            )
        audio_path = manifest_path.parent / relative_path
        if not audio_path.is_file():
            raise FileNotFoundError(f"Benchmark audio is missing: {audio_path}")
        resolved_items.append({**item, "audio_path": audio_path})
    return manifest, resolved_items


def read_pcm16_wav(path: Path):
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        compression = source.getcomptype()
        frames = source.readframes(frame_count)

    if sample_width != 2 or compression != "NONE":
        raise ValueError(f"Expected uncompressed PCM16 WAV: {path}")
    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).astype(np.int32)
        samples = np.mean(samples, axis=1).astype(np.int16)
    duration = frame_count / sample_rate
    return samples.tobytes(), sample_rate, duration


def backend_builder(args):
    """Resolve imports before timing and return a model-loading callable."""
    if args.backend == "faster-whisper":
        from src.stt_whisper import STTWhisper

        return lambda: STTWhisper(
            model=args.model,
            compute_type=args.compute_type,
            device=args.device,
            language=args.language,
            beam_size=args.beam_size,
        )

    from src.stt_mlx import MLXWhisperBackend, _load_mlx_runtime

    transcribe_fn, model_loader = _load_mlx_runtime()

    return lambda: MLXWhisperBackend(
        model=args.model,
        language=args.language,
        beam_size=args.beam_size,
        transcribe_fn=transcribe_fn,
        model_loader=model_loader,
    )


def package_version(name: str):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def max_rss_bytes():
    if resource is None:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def default_output_path(args) -> Path:
    safe_model = args.model.replace("/", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("benchmarks/local_stt_results") / (
        f"{args.backend}_{safe_model}_{timestamp}.json"
    )


def main() -> int:
    args = parse_args()
    manifest = None
    items = None
    if not args.prepare_only:
        manifest, items = load_manifest(args.manifest)
        os.environ["HF_HUB_OFFLINE"] = "1"

    build_backend = backend_builder(args)
    load_started = time.perf_counter()
    backend = build_backend()
    model_load_seconds = time.perf_counter() - load_started
    if args.prepare_only:
        print(
            f"Prepared {args.backend} model {args.model} in "
            f"{model_load_seconds:.3f}s; run again without --prepare-only to benchmark."
        )
        return 0

    loaded_items = []
    for item in items:
        audio_bytes, sample_rate, duration = read_pcm16_wav(item["audio_path"])
        loaded_items.append(
            {
                **item,
                "audio_bytes": audio_bytes,
                "sample_rate": sample_rate,
                "duration_seconds": duration,
            }
        )

    warmup_item = loaded_items[0]
    warmup_started = time.perf_counter()
    warmup_text = backend.transcribe(
        warmup_item["audio_bytes"], warmup_item["sample_rate"]
    )
    warmup_seconds = time.perf_counter() - warmup_started

    results = []
    total_audio_seconds = 0.0
    total_inference_seconds = 0.0
    total_word_errors = 0
    total_reference_words = 0
    total_character_errors = 0
    total_reference_characters = 0

    for item in loaded_items:
        started = time.perf_counter()
        text = backend.transcribe(item["audio_bytes"], item["sample_rate"])
        inference_seconds = time.perf_counter() - started
        hypothesis = text or ""
        word_errors, reference_words = word_error_counts(
            item["reference_text"], hypothesis
        )
        character_errors, reference_characters = character_error_counts(
            item["reference_text"], hypothesis
        )
        total_audio_seconds += item["duration_seconds"]
        total_inference_seconds += inference_seconds
        total_word_errors += word_errors
        total_reference_words += reference_words
        total_character_errors += character_errors
        total_reference_characters += reference_characters
        results.append(
            {
                "id": item["id"],
                "category": item["category"],
                "audio_filename": item["audio_filename"],
                "reference_text": item["reference_text"],
                "output_text": hypothesis,
                "audio_duration_seconds": item["duration_seconds"],
                "inference_seconds": inference_seconds,
                "rtf": inference_seconds / item["duration_seconds"],
                "word_errors": word_errors,
                "reference_words": reference_words,
                "character_errors": character_errors,
                "reference_characters": reference_characters,
                "error": None if text else "empty transcription",
            }
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "model": args.model,
        "language": args.language,
        "device": "metal" if args.backend == "mlx-whisper" else args.device,
        "compute_type": (
            "float16" if args.backend == "mlx-whisper" else args.compute_type
        ),
        "decoding": {
            "beam_size": (
                None if args.backend == "mlx-whisper" else args.beam_size
            ),
            "requested_beam_size": args.beam_size,
            "strategy": (
                "greedy (mlx-whisper 0.4.3 has no beam decoder)"
                if args.backend == "mlx-whisper"
                else "beam_size=1"
            ),
            "temperature": 0.0 if args.backend == "mlx-whisper" else "backend default",
            "presegmented_input": True,
            "backend_vad": False,
        },
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "packages": {
                name: package_version(name)
                for name in (
                    "mlx-whisper",
                    "mlx",
                    "faster-whisper",
                    "ctranslate2",
                    "numpy",
                )
            },
        },
        "manifest": str(args.manifest),
        "offline_cache_only": not args.prepare_only,
        "model_load_seconds": model_load_seconds,
        "warmup": {
            "item_id": warmup_item["id"],
            "seconds": warmup_seconds,
            "output_text": warmup_text or "",
            "counted_in_totals": False,
        },
        "corpus": {
            "utterance_count": len(results),
            "total_audio_seconds": total_audio_seconds,
            "total_inference_seconds": total_inference_seconds,
            "rtf": total_inference_seconds / total_audio_seconds,
            "word_errors": total_word_errors,
            "reference_words": total_reference_words,
            "wer": total_word_errors / max(1, total_reference_words),
            "character_errors": total_character_errors,
            "reference_characters": total_reference_characters,
            "cer": total_character_errors / max(1, total_reference_characters),
        },
        "process_peak_rss_bytes": max_rss_bytes(),
        "utterances": results,
    }

    output_path = args.output or default_output_path(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    corpus = report["corpus"]
    print(f"Backend/model: {args.backend} / {args.model}")
    print(f"Model load: {model_load_seconds:.3f}s")
    print(f"Warm-up (excluded): {warmup_seconds:.3f}s")
    print(
        f"Corpus: {corpus['utterance_count']} utterances, "
        f"{corpus['total_audio_seconds']:.3f}s audio"
    )
    print(
        f"Inference: {corpus['total_inference_seconds']:.3f}s, "
        f"RTF={corpus['rtf']:.4f}, WER={corpus['wer']:.4f}, "
        f"CER={corpus['cer']:.4f}"
    )
    print(f"JSON: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
