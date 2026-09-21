#!/usr/bin/env python3
"""Bounded microphone -> BlackHole routing and loopback diagnostic.

This script is deliberately independent of the production translation pipeline.
It never writes audio to disk and never changes system audio defaults.
"""

from __future__ import annotations

import argparse
import math
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SAMPLE_RATE = 48_000
BLOCK_SIZE = 480
DEFAULT_QUEUE_BLOCKS = 50
DEFAULT_PREFILL_BLOCKS = 6
SIGNAL_THRESHOLD = 1e-5


class DiagnosticError(RuntimeError):
    """Raised for a safe, user-actionable diagnostic failure."""


def device_supports_direction(device: Mapping[str, Any], direction: str) -> bool:
    """Return whether a device has channels in the requested direction."""
    key = "max_input_channels" if direction == "input" else "max_output_channels"
    return int(device.get(key, 0)) > 0


def match_device(
    devices: Iterable[Mapping[str, Any]], name: str, direction: str
) -> Mapping[str, Any]:
    """Resolve one capable device, preferring a unique exact name match."""
    if direction not in {"input", "output"}:
        raise ValueError("direction must be 'input' or 'output'")
    needle = name.strip().casefold()
    if not needle:
        raise DiagnosticError(f"{direction} device name must not be empty")

    capable = [
        device
        for device in devices
        if device_supports_direction(device, direction)
    ]
    exact = [device for device in capable if str(device["name"]).casefold() == needle]
    matches = exact or [
        device for device in capable if needle in str(device["name"]).casefold()
    ]

    if not matches:
        available = ", ".join(str(device["name"]) for device in capable) or "none"
        raise DiagnosticError(
            f"No {direction} device matched {name!r}. Available: {available}"
        )
    if len(matches) > 1:
        matched = ", ".join(
            f"[{device['index']}] {device['name']}" for device in matches
        )
        raise DiagnosticError(
            f"Ambiguous {direction} device match {name!r}: {matched}. "
            "Use a more specific name."
        )
    return matches[0]


def mono_to_stereo(mono: np.ndarray, stereo: np.ndarray) -> None:
    """Copy an (N, 1) mono block into both channels of an (N, 2) block."""
    if mono.ndim != 2 or mono.shape[1] != 1:
        raise ValueError("mono input must have shape (frames, 1)")
    if stereo.shape != (mono.shape[0], 2):
        raise ValueError("stereo output must have shape (frames, 2)")
    stereo[:, 0] = mono[:, 0]
    stereo[:, 1] = mono[:, 0]


@dataclass
class SignalMetrics:
    """Streaming signal statistics that retain no audio samples."""

    frames: int = 0
    samples: int = 0
    sum_squares: float = 0.0
    peak: float = 0.0
    signal_blocks: int = 0

    def observe(self, audio: np.ndarray, threshold: float = SIGNAL_THRESHOLD) -> None:
        values = np.asarray(audio, dtype=np.float32)
        if values.size == 0:
            return
        block_peak = float(np.max(np.abs(values)))
        flattened = values.reshape(-1).astype(np.float64, copy=False)
        self.frames += int(values.shape[0])
        self.samples += int(values.size)
        self.sum_squares += float(np.dot(flattened, flattened))
        self.peak = max(self.peak, block_peak)
        if block_peak > threshold:
            self.signal_blocks += 1

    @property
    def rms(self) -> float:
        if not self.samples:
            return 0.0
        return math.sqrt(self.sum_squares / self.samples)


@dataclass
class RoutingMetrics:
    """Counters shared by the three PortAudio callbacks."""

    source_callbacks: int = 0
    output_callbacks: int = 0
    loopback_callbacks: int = 0
    queue_high_water: int = 0
    queue_final_depth: int = 0
    queue_overflows: int = 0
    queue_underflows: int = 0
    input_overflows: int = 0
    loopback_input_overflows: int = 0
    output_underflows: int = 0
    dropped_chunks: int = 0
    latency_observations: int = 0
    latency_sum_seconds: float = 0.0
    latency_min_seconds: float = math.inf
    latency_max_seconds: float = 0.0
    source: SignalMetrics = field(default_factory=SignalMetrics)
    submitted: SignalMetrics = field(default_factory=SignalMetrics)
    loopback: SignalMetrics = field(default_factory=SignalMetrics)

    def observe_latency(self, captured_at: float, submitted_at: float) -> None:
        latency = submitted_at - captured_at
        if captured_at <= 0 or submitted_at <= 0 or not math.isfinite(latency) or latency < 0:
            return
        self.latency_observations += 1
        self.latency_sum_seconds += latency
        self.latency_min_seconds = min(self.latency_min_seconds, latency)
        self.latency_max_seconds = max(self.latency_max_seconds, latency)


class BoundedAudioQueue:
    """A fail-visible queue that never evicts previously captured speech."""

    def __init__(self, capacity: int, metrics: RoutingMetrics):
        if capacity < 1:
            raise ValueError("queue capacity must be at least 1")
        self._queue: queue.Queue[tuple[np.ndarray, float]] = queue.Queue(maxsize=capacity)
        self.metrics = metrics

    def put(self, block: np.ndarray, captured_at: float = 0.0) -> bool:
        try:
            self._queue.put_nowait((block, captured_at))
        except queue.Full:
            self.metrics.queue_overflows += 1
            self.metrics.dropped_chunks += 1
            return False
        self.metrics.queue_high_water = max(
            self.metrics.queue_high_water, self._queue.qsize()
        )
        return True

    def get(self) -> tuple[np.ndarray, float]:
        return self._queue.get_nowait()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()


@dataclass(frozen=True)
class RoutingConfig:
    input_name: str
    output_name: str
    duration: float = 10.0
    sample_rate: int = SAMPLE_RATE
    block_size: int = BLOCK_SIZE
    queue_blocks: int = DEFAULT_QUEUE_BLOCKS
    prefill_blocks: int = DEFAULT_PREFILL_BLOCKS
    start_delay: float = 0.0

    def validate(self) -> None:
        if not self.input_name.strip() or not self.output_name.strip():
            raise DiagnosticError("input and output names must not be empty")
        if not 0 < self.duration <= 300:
            raise DiagnosticError("duration must be greater than 0 and at most 300 seconds")
        if self.sample_rate != SAMPLE_RATE:
            raise DiagnosticError("Phase 2 routing must use 48000 Hz")
        if self.block_size < 1:
            raise DiagnosticError("block size must be positive")
        if self.queue_blocks < 2:
            raise DiagnosticError("queue capacity must be at least 2 blocks")
        if not 1 <= self.prefill_blocks < self.queue_blocks:
            raise DiagnosticError("prefill blocks must be at least 1 and below capacity")
        if not 0 <= self.start_delay <= 30:
            raise DiagnosticError("start delay must be between 0 and 30 seconds")


def enumerate_devices(sd: Any) -> list[dict[str, Any]]:
    """Return PortAudio devices with stable descriptive fields."""
    hostapis = sd.query_hostapis()
    records = []
    for index, raw in enumerate(sd.query_devices()):
        records.append(
            {
                "index": index,
                "name": raw["name"],
                "hostapi": hostapis[raw["hostapi"]]["name"],
                "max_input_channels": int(raw["max_input_channels"]),
                "max_output_channels": int(raw["max_output_channels"]),
                "default_samplerate": float(raw["default_samplerate"]),
            }
        )
    return records


def print_devices(devices: Sequence[Mapping[str, Any]]) -> None:
    print("INPUT DEVICES")
    for device in devices:
        if device_supports_direction(device, "input"):
            print(
                f"  [{device['index']}] {device['name']} | "
                f"in={device['max_input_channels']} out={device['max_output_channels']} | "
                f"{device['default_samplerate']:.0f} Hz | {device['hostapi']}"
            )
    print("OUTPUT DEVICES")
    for device in devices:
        if device_supports_direction(device, "output"):
            print(
                f"  [{device['index']}] {device['name']} | "
                f"in={device['max_input_channels']} out={device['max_output_channels']} | "
                f"{device['default_samplerate']:.0f} Hz | {device['hostapi']}"
            )


def describe_device(label: str, device: Mapping[str, Any]) -> None:
    print(
        f"{label}: [{device['index']}] {device['name']} | {device['hostapi']} | "
        f"in={device['max_input_channels']} out={device['max_output_channels']} | "
        f"default={device['default_samplerate']:.0f} Hz"
    )


def validate_devices(
    sd: Any,
    source: Mapping[str, Any],
    blackhole: Mapping[str, Any],
    config: RoutingConfig,
) -> None:
    if str(source["hostapi"]).casefold() != "core audio":
        raise DiagnosticError("source device is not using the Core Audio host API")
    if str(blackhole["hostapi"]).casefold() != "core audio":
        raise DiagnosticError("BlackHole device is not using the Core Audio host API")
    if int(source["max_input_channels"]) < 1:
        raise DiagnosticError("source device has no input channel")
    if int(blackhole["max_input_channels"]) < 2:
        raise DiagnosticError("BlackHole device needs at least two input channels")
    if int(blackhole["max_output_channels"]) < 2:
        raise DiagnosticError("BlackHole device needs at least two output channels")
    sd.check_input_settings(
        device=source["index"], channels=1, dtype="float32", samplerate=config.sample_rate
    )
    sd.check_output_settings(
        device=blackhole["index"], channels=2, dtype="float32", samplerate=config.sample_rate
    )
    sd.check_input_settings(
        device=blackhole["index"], channels=2, dtype="float32", samplerate=config.sample_rate
    )


def baseline_failures(
    metrics: RoutingMetrics, fatal_reasons: Sequence[str]
) -> list[str]:
    failures = list(fatal_reasons)
    if metrics.source_callbacks == 0 or metrics.source.frames == 0:
        failures.append("microphone callback produced no frames")
    if metrics.output_callbacks == 0 or metrics.submitted.frames == 0:
        failures.append("no frames were submitted to BlackHole output")
    if metrics.loopback_callbacks == 0 or metrics.loopback.frames == 0:
        failures.append("BlackHole input callback produced no frames after output started")
    if metrics.source.signal_blocks == 0:
        failures.append("no non-zero microphone signal was observed")
    if metrics.submitted.signal_blocks == 0:
        failures.append("no non-zero signal was submitted to BlackHole")
    if metrics.loopback.signal_blocks == 0:
        failures.append("no non-zero signal was observed on BlackHole input after output started")
    if metrics.queue_final_depth:
        failures.append(
            f"routing queue retained {metrics.queue_final_depth} unsubmitted block(s)"
        )
    if metrics.source.frames != metrics.submitted.frames:
        failures.append(
            "captured/submitted frame mismatch: "
            f"{metrics.source.frames}/{metrics.submitted.frames}"
        )
    if metrics.submitted.rms > SIGNAL_THRESHOLD and metrics.loopback.rms > 0:
        rms_ratio = metrics.loopback.rms / metrics.submitted.rms
        if not 0.8 <= rms_ratio <= 1.2:
            failures.append(
                f"BlackHole loopback/output RMS ratio is inconsistent: {rms_ratio:.3f}"
            )
    if metrics.submitted.peak > SIGNAL_THRESHOLD and metrics.loopback.peak > 0:
        peak_ratio = metrics.loopback.peak / metrics.submitted.peak
        if not 0.8 <= peak_ratio <= 1.2:
            failures.append(
                f"BlackHole loopback/output peak ratio is inconsistent: {peak_ratio:.3f}"
            )
    health = {
        "input overflows": metrics.input_overflows,
        "BlackHole input overflows": metrics.loopback_input_overflows,
        "output underflows": metrics.output_underflows,
        "queue underflows": metrics.queue_underflows,
        "queue overflows": metrics.queue_overflows,
        "dropped chunks": metrics.dropped_chunks,
    }
    failures.extend(f"{name}: {count}" for name, count in health.items() if count)
    return failures


def print_metrics(metrics: RoutingMetrics, runtime: float) -> None:
    print("\nAUDIO METRICS")
    print(f"  runtime_seconds: {runtime:.3f}")
    print(f"  source_callbacks: {metrics.source_callbacks}")
    print(f"  output_callbacks: {metrics.output_callbacks}")
    print(f"  loopback_callbacks: {metrics.loopback_callbacks}")
    print(f"  source_frames: {metrics.source.frames}")
    print(f"  output_frames_submitted: {metrics.submitted.frames}")
    print(f"  loopback_frames: {metrics.loopback.frames}")
    print(f"  source_rms: {metrics.source.rms:.8f}")
    print(f"  source_peak: {metrics.source.peak:.8f}")
    print(f"  source_signal_blocks: {metrics.source.signal_blocks}")
    print(f"  blackhole_output_rms: {metrics.submitted.rms:.8f}")
    print(f"  blackhole_output_peak: {metrics.submitted.peak:.8f}")
    print(f"  blackhole_output_signal_blocks: {metrics.submitted.signal_blocks}")
    print(f"  blackhole_input_rms: {metrics.loopback.rms:.8f}")
    print(f"  blackhole_input_peak: {metrics.loopback.peak:.8f}")
    print(f"  blackhole_input_signal_blocks_after_output_start: {metrics.loopback.signal_blocks}")
    if metrics.submitted.rms > 0:
        print(f"  blackhole_loopback_output_rms_ratio: {metrics.loopback.rms / metrics.submitted.rms:.6f}")
    if metrics.submitted.peak > 0:
        print(f"  blackhole_loopback_output_peak_ratio: {metrics.loopback.peak / metrics.submitted.peak:.6f}")
    if metrics.latency_observations:
        latency_mean = metrics.latency_sum_seconds / metrics.latency_observations
        print(f"  capture_to_playback_latency_ms_mean: {latency_mean * 1000:.3f}")
        print(f"  capture_to_playback_latency_ms_min: {metrics.latency_min_seconds * 1000:.3f}")
        print(f"  capture_to_playback_latency_ms_max: {metrics.latency_max_seconds * 1000:.3f}")
        print(f"  capture_to_playback_latency_observations: {metrics.latency_observations}")
    else:
        print("  capture_to_playback_latency_ms: unavailable (no valid PortAudio timestamps)")
    print("\nQUEUE / STREAM HEALTH")
    print(f"  queue_high_water_blocks: {metrics.queue_high_water}")
    print(f"  queue_final_depth_blocks: {metrics.queue_final_depth}")
    print(f"  input_overflows: {metrics.input_overflows}")
    print(f"  blackhole_input_overflows: {metrics.loopback_input_overflows}")
    print(f"  output_underflows: {metrics.output_underflows}")
    print(f"  queue_underflows: {metrics.queue_underflows}")
    print(f"  queue_overflows: {metrics.queue_overflows}")
    print(f"  dropped_chunks: {metrics.dropped_chunks}")


def run_routing(sd: Any, config: RoutingConfig) -> tuple[RoutingMetrics, float, list[str]]:
    """Run one finite, memory-only routing and loopback observation."""
    config.validate()
    devices = enumerate_devices(sd)
    source = match_device(devices, config.input_name, "input")
    blackhole_output = match_device(devices, config.output_name, "output")
    # Require the loopback observer to use the exact same device identity/name.
    blackhole_input = match_device(devices, str(blackhole_output["name"]), "input")
    if blackhole_input["index"] != blackhole_output["index"]:
        raise DiagnosticError("BlackHole input and output did not resolve to one device")
    if source["index"] == blackhole_output["index"]:
        raise DiagnosticError("input source must not be the BlackHole output device")

    validate_devices(sd, source, blackhole_output, config)
    print("ROUTING TOPOLOGY")
    describe_device("  microphone", source)
    describe_device("  BlackHole output + loopback input", blackhole_output)
    print(
        f"  format: mono -> explicit stereo, float32, {config.sample_rate} Hz, "
        f"{config.block_size}-frame blocks"
    )
    print("  prohibited path: BlackHole input is observed only and never routed to output")

    metrics = RoutingMetrics()
    audio_queue = BoundedAudioQueue(config.queue_blocks, metrics)
    fatal_event = threading.Event()
    output_started = threading.Event()
    source_stopping = threading.Event()
    source_finished = threading.Event()
    fatal_reasons: list[str] = []

    def fail(reason: str) -> None:
        if reason not in fatal_reasons:
            fatal_reasons.append(reason)
        fatal_event.set()

    def source_callback(indata: np.ndarray, frames: int, timing: Any, status: Any) -> None:
        metrics.source_callbacks += 1
        if status.input_overflow:
            metrics.input_overflows += 1
            fail("PortAudio reported microphone input overflow")
        if frames != config.block_size:
            fail(f"microphone callback returned {frames} frames, expected {config.block_size}")
        metrics.source.observe(indata)
        captured_at = float(getattr(timing, "inputBufferAdcTime", 0.0))
        if not audio_queue.put(indata.copy(), captured_at):
            fail("routing queue filled; current microphone chunk was not enqueued")
            raise sd.CallbackAbort

    def output_callback(outdata: np.ndarray, frames: int, timing: Any, status: Any) -> None:
        metrics.output_callbacks += 1
        if status.output_underflow:
            metrics.output_underflows += 1
            fail("PortAudio reported BlackHole output underflow")
        if frames != config.block_size:
            fail(f"output callback requested {frames} frames, expected {config.block_size}")
        try:
            mono, captured_at = audio_queue.get()
        except queue.Empty:
            outdata.fill(0)
            if source_finished.is_set():
                raise sd.CallbackStop
            if source_stopping.is_set():
                # The producer has been asked to stop, but PortAudio has not yet
                # returned from stop(). This terminal callback is not active-run
                # starvation; keep the output quiet until the state is final.
                return
            metrics.queue_underflows += 1
            fail("routing queue starved while microphone capture was active")
            raise sd.CallbackAbort
        mono_to_stereo(mono, outdata)
        metrics.submitted.observe(outdata)
        submitted_at = float(getattr(timing, "outputBufferDacTime", 0.0))
        metrics.observe_latency(captured_at, submitted_at)

    def loopback_callback(indata: np.ndarray, frames: int, timing: Any, status: Any) -> None:
        del timing
        metrics.loopback_callbacks += 1
        if status.input_overflow:
            metrics.loopback_input_overflows += 1
            fail("PortAudio reported BlackHole input overflow")
        if frames != config.block_size:
            fail(f"loopback callback returned {frames} frames, expected {config.block_size}")
        if output_started.is_set():
            metrics.loopback.observe(indata)

    if config.start_delay:
        print(f"Starting capture in {config.start_delay:.1f}s; speak normally during the test.")
        time.sleep(config.start_delay)

    runtime = 0.0
    loopback_stream = source_stream = output_stream = None
    try:
        loopback_stream = sd.InputStream(
            device=blackhole_input["index"],
            channels=2,
            samplerate=config.sample_rate,
            dtype="float32",
            blocksize=config.block_size,
            latency="low",
            callback=loopback_callback,
        )
        source_stream = sd.InputStream(
            device=source["index"],
            channels=1,
            samplerate=config.sample_rate,
            dtype="float32",
            blocksize=config.block_size,
            latency="low",
            callback=source_callback,
        )
        output_stream = sd.OutputStream(
            device=blackhole_output["index"],
            channels=2,
            samplerate=config.sample_rate,
            dtype="float32",
            blocksize=config.block_size,
            latency="low",
            callback=output_callback,
        )

        loopback_stream.start()
        source_stream.start()
        prefill_deadline = time.monotonic() + 2.0
        while audio_queue.qsize() < config.prefill_blocks and not fatal_event.is_set():
            if time.monotonic() >= prefill_deadline:
                fail("microphone queue did not prefill within 2 seconds")
                break
            time.sleep(0.005)
        if fatal_event.is_set():
            raise DiagnosticError(fatal_reasons[0])

        output_started.set()
        output_stream.start()
        started = time.monotonic()
        deadline = started + config.duration
        while time.monotonic() < deadline and not fatal_event.is_set():
            if not source_stream.active:
                fail("microphone stream became inactive during the bounded run")
                break
            if not output_stream.active:
                fail("BlackHole output stream became inactive during the bounded run")
                break
            if not loopback_stream.active:
                fail("BlackHole input stream became inactive during the bounded run")
                break
            time.sleep(0.02)
        runtime = time.monotonic() - started

        source_stopping.set()
        source_stream.stop()
        source_finished.set()
        drain_deadline = time.monotonic() + max(1.0, config.queue_blocks * config.block_size / config.sample_rate)
        while output_stream.active and not fatal_event.is_set():
            if time.monotonic() >= drain_deadline:
                fail("BlackHole output did not drain within the bounded timeout")
                break
            time.sleep(0.005)
        time.sleep(2 * config.block_size / config.sample_rate)
        if not loopback_stream.active:
            fail("BlackHole input stream stopped before output-tail observation completed")
    finally:
        source_finished.set()
        streams = (
            ("BlackHole output", output_stream),
            ("microphone input", source_stream),
            ("BlackHole input", loopback_stream),
        )
        for label, stream in streams:
            if stream is not None:
                try:
                    stream.stop()
                except Exception as exc:
                    fail(f"failed to stop {label} stream: {exc}")
                try:
                    stream.close()
                except Exception as exc:
                    fail(f"failed to close {label} stream: {exc}")

    metrics.queue_final_depth = audio_queue.qsize()
    failures = baseline_failures(metrics, fatal_reasons)
    return metrics, runtime, failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route a named microphone to BlackHole and verify its loopback in memory."
    )
    parser.add_argument("--list-devices", action="store_true", help="list devices and exit")
    parser.add_argument("--duration", type=float, default=10.0, help="bounded run time in seconds")
    parser.add_argument(
        "--input-name", default="MacBook Pro Mikrofonu", help="microphone name substring"
    )
    parser.add_argument(
        "--output-name", default="BlackHole 2ch", help="BlackHole output name substring"
    )
    parser.add_argument("--queue-blocks", type=int, default=DEFAULT_QUEUE_BLOCKS)
    parser.add_argument("--prefill-blocks", type=int, default=DEFAULT_PREFILL_BLOCKS)
    parser.add_argument(
        "--start-delay",
        type=float,
        default=0.0,
        help="delay before opening streams; useful for preparing to speak",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        import sounddevice as sd
    except ImportError:
        print("FAIL: sounddevice is not installed in this Python environment", file=sys.stderr)
        return 2

    try:
        devices = enumerate_devices(sd)
        if args.list_devices:
            print_devices(devices)
            return 0
        config = RoutingConfig(
            input_name=args.input_name,
            output_name=args.output_name,
            duration=args.duration,
            queue_blocks=args.queue_blocks,
            prefill_blocks=args.prefill_blocks,
            start_delay=args.start_delay,
        )
        metrics, runtime, failures = run_routing(sd, config)
        print_metrics(metrics, runtime)
        if failures:
            print("\nPHASE 2 ROUTING DIAGNOSTIC: FAIL")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("\nPHASE 2 ROUTING DIAGNOSTIC: PASS")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted; stream closure was attempted and no audio was retained.", file=sys.stderr)
        return 130
    except (DiagnosticError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAIL: audio diagnostic error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
