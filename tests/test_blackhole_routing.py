"""Pure-logic tests for the standalone BlackHole routing diagnostic."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

import numpy as np


SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "test_blackhole_routing.py"
SPEC = importlib.util.spec_from_file_location("test_blackhole_routing_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ROUTING = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ROUTING
SPEC.loader.exec_module(ROUTING)


def device(index, name, inputs, outputs):
    return {
        "index": index,
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
    }


class DeviceMatchingTests(unittest.TestCase):
    def setUp(self):
        self.devices = [
            device(0, "MacBook Pro Mikrofonu", 1, 0),
            device(1, "BlackHole 2ch", 2, 2),
            device(2, "BlackHole 16ch", 16, 16),
        ]

    def test_unique_substring_match(self):
        matched = ROUTING.match_device(self.devices, "Mikrofonu", "input")
        self.assertEqual(matched["index"], 0)

    def test_exact_match_wins_over_other_substrings(self):
        matched = ROUTING.match_device(self.devices, "BlackHole 2ch", "output")
        self.assertEqual(matched["index"], 1)

    def test_ambiguous_substring_fails(self):
        with self.assertRaises(ROUTING.DiagnosticError):
            ROUTING.match_device(self.devices, "BlackHole", "output")

    def test_wrong_direction_does_not_match(self):
        with self.assertRaises(ROUTING.DiagnosticError):
            ROUTING.match_device([device(0, "Speaker", 0, 2)], "Speaker", "input")


class ConversionAndMetricsTests(unittest.TestCase):
    def test_mono_is_copied_to_both_stereo_channels(self):
        mono = np.array([[0.25], [-0.5], [0.75]], dtype=np.float32)
        stereo = np.zeros((3, 2), dtype=np.float32)
        ROUTING.mono_to_stereo(mono, stereo)
        np.testing.assert_array_equal(stereo[:, 0], mono[:, 0])
        np.testing.assert_array_equal(stereo[:, 1], mono[:, 0])

    def test_signal_metrics_compute_peak_and_rms(self):
        metrics = ROUTING.SignalMetrics()
        metrics.observe(np.array([[1.0], [-1.0], [0.0], [0.0]], dtype=np.float32))
        self.assertAlmostEqual(metrics.peak, 1.0)
        self.assertAlmostEqual(metrics.rms, 2 ** -0.5)
        self.assertEqual(metrics.frames, 4)
        self.assertEqual(metrics.signal_blocks, 1)


class BackpressureTests(unittest.TestCase):
    def test_full_queue_preserves_oldest_and_records_visible_drop(self):
        metrics = ROUTING.RoutingMetrics()
        audio_queue = ROUTING.BoundedAudioQueue(1, metrics)
        first = np.array([[0.1]], dtype=np.float32)
        second = np.array([[0.2]], dtype=np.float32)
        self.assertTrue(audio_queue.put(first))
        self.assertFalse(audio_queue.put(second))
        queued, captured_at = audio_queue.get()
        np.testing.assert_array_equal(queued, first)
        self.assertEqual(captured_at, 0.0)
        self.assertEqual(metrics.queue_overflows, 1)
        self.assertEqual(metrics.dropped_chunks, 1)
        self.assertEqual(metrics.queue_high_water, 1)


class ConfigurationTests(unittest.TestCase):
    def test_default_configuration_is_valid(self):
        ROUTING.RoutingConfig("Mic", "BlackHole").validate()

    def test_invalid_duration_fails(self):
        with self.assertRaises(ROUTING.DiagnosticError):
            ROUTING.RoutingConfig("Mic", "BlackHole", duration=0).validate()

    def test_prefill_must_be_below_capacity(self):
        with self.assertRaises(ROUTING.DiagnosticError):
            ROUTING.RoutingConfig(
                "Mic", "BlackHole", queue_blocks=4, prefill_blocks=4
            ).validate()


class LatencyMetricsTests(unittest.TestCase):
    def test_valid_portaudio_timestamps_are_aggregated(self):
        metrics = ROUTING.RoutingMetrics()
        metrics.observe_latency(100.0, 100.025)
        self.assertEqual(metrics.latency_observations, 1)
        self.assertAlmostEqual(metrics.latency_min_seconds, 0.025)
        self.assertAlmostEqual(metrics.latency_max_seconds, 0.025)

    def test_invalid_timestamps_are_ignored(self):
        metrics = ROUTING.RoutingMetrics()
        metrics.observe_latency(0.0, 1.0)
        metrics.observe_latency(2.0, 1.0)
        self.assertEqual(metrics.latency_observations, 0)


class BaselineAcceptanceTests(unittest.TestCase):
    def healthy_metrics(self):
        metrics = ROUTING.RoutingMetrics(
            source_callbacks=1,
            output_callbacks=1,
            loopback_callbacks=1,
        )
        signal = np.array([[0.25], [-0.25]], dtype=np.float32)
        stereo = np.column_stack([signal, signal])
        metrics.source.observe(signal)
        metrics.submitted.observe(stereo)
        metrics.loopback.observe(stereo)
        return metrics

    def test_healthy_metrics_pass(self):
        self.assertEqual(ROUTING.baseline_failures(self.healthy_metrics(), []), [])

    def test_nonempty_final_queue_fails(self):
        metrics = self.healthy_metrics()
        metrics.queue_final_depth = 3
        failures = ROUTING.baseline_failures(metrics, [])
        self.assertTrue(any("unsubmitted" in failure for failure in failures))

    def test_captured_submitted_frame_mismatch_fails(self):
        metrics = self.healthy_metrics()
        metrics.source.frames += 1
        failures = ROUTING.baseline_failures(metrics, [])
        self.assertTrue(any("frame mismatch" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
