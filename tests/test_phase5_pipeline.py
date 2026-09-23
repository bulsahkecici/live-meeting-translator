import queue
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from src.audio_in import AudioInput
from src.audio_out import AudioOutput
from src.backend_factory import PipelineComponents
from src.pipeline import TranslationPipeline
from src.pipeline_runtime import (
    PipelineBackpressureError,
    PipelineMessage,
    PipelineRuntime,
)


class OrderedWorkerRuntimeTests(unittest.TestCase):
    def test_order_is_preserved_across_all_stage_workers(self):
        calls = {name: [] for name in ("stt", "translation", "tts", "playback")}
        completed = []

        def handler(name):
            def run(message):
                calls[name].append(message.sequence_id)
                return True
            return run

        runtime = PipelineRuntime(
            tuple((name, handler(name)) for name in calls),
            queue_capacity=2,
            on_complete=lambda message: completed.append(message.sequence_id),
        )
        runtime.start()
        for value in (b"one", b"two", b"three"):
            runtime.submit(value)
        runtime.shutdown(drain=True)

        self.assertEqual(completed, [1, 2, 3])
        for stage_calls in calls.values():
            self.assertEqual(stage_calls, [1, 2, 3])
        metrics = runtime.snapshot()
        self.assertEqual(metrics["submitted"], 3)
        self.assertEqual(metrics["completed"], 3)
        self.assertEqual(metrics["failed"], 0)
        self.assertEqual(metrics["workers_alive"], [])
        self.assertTrue(all(depth == 0 for depth in metrics["queue_depth"].values()))

    def test_ingress_saturation_fails_without_evicting_queued_speech(self):
        entered = threading.Event()
        release = threading.Event()
        completed = []

        def blocked_handler(message):
            if message.sequence_id == 1:
                entered.set()
                release.wait(2)
            return True

        runtime = PipelineRuntime(
            (("stt", blocked_handler),),
            queue_capacity=1,
            enqueue_timeout_seconds=0.02,
            on_complete=lambda message: completed.append(message.sequence_id),
        )
        runtime.start()
        runtime.submit(b"first")
        self.assertTrue(entered.wait(1))
        runtime.submit(b"second")
        with self.assertRaisesRegex(
            PipelineBackpressureError, "rather than deleting queued speech"
        ):
            runtime.submit(b"third")
        release.set()
        runtime.shutdown(drain=True)

        self.assertEqual(completed, [1, 2])
        metrics = runtime.snapshot()
        self.assertEqual(metrics["submitted"], 2)
        self.assertEqual(metrics["overload_failures"], 1)

    def test_stage_failure_is_contained_and_later_item_completes(self):
        downstream = []
        failures = []
        completed = []

        def translation(message):
            return message.sequence_id != 1

        def playback(message):
            downstream.append(message.sequence_id)
            return True

        runtime = PipelineRuntime(
            (("translation", translation), ("playback", playback)),
            on_failure=lambda message: failures.append(message.sequence_id),
            on_complete=lambda message: completed.append(message.sequence_id),
        )
        runtime.start()
        runtime.submit(b"first")
        runtime.submit(b"second")
        runtime.shutdown(drain=True)

        self.assertEqual(failures, [1])
        self.assertEqual(downstream, [2])
        self.assertEqual(completed, [2])
        self.assertEqual(runtime.snapshot()["failed"], 1)

    def test_stage_exception_is_contained_and_later_item_completes(self):
        completed = []
        failed = []

        def handler(message):
            if message.sequence_id == 1:
                raise RuntimeError("backend exploded")
            return True

        runtime = PipelineRuntime(
            (("stage", handler),),
            on_complete=lambda message: completed.append(message.sequence_id),
            on_failure=lambda message: failed.append(message.sequence_id),
        )
        runtime.start()
        runtime.submit(b"first")
        runtime.submit(b"second")
        with self.assertLogs("src.pipeline_runtime", level="ERROR"):
            runtime.shutdown(drain=True)

        self.assertEqual(failed, [1])
        self.assertEqual(completed, [2])
        self.assertEqual(runtime.snapshot()["workers_alive"], [])

    def test_shutdown_drain_waits_beyond_live_timeout_and_keeps_sentinel_last(self):
        entered = threading.Event()
        release = threading.Event()
        completed_audio = []

        def handler(message):
            if message.audio_bytes == b"first":
                entered.set()
                release.wait(2)
            return True

        runtime = PipelineRuntime(
            (("stt", handler),),
            queue_capacity=1,
            enqueue_timeout_seconds=0.01,
            shutdown_timeout_seconds=2,
            on_complete=lambda message: completed_audio.append(message.audio_bytes),
        )
        runtime.start()
        runtime.submit(b"first")
        self.assertTrue(entered.wait(1))
        runtime.submit(b"second")

        draining_submit = threading.Thread(
            target=runtime.submit_for_drain,
            args=(b"third",),
        )
        draining_submit.start()
        time.sleep(0.03)
        self.assertTrue(draining_submit.is_alive())

        shutdown = threading.Thread(target=runtime.shutdown)
        shutdown.start()
        time.sleep(0.02)
        self.assertTrue(shutdown.is_alive())
        release.set()
        draining_submit.join(2)
        shutdown.join(2)

        self.assertFalse(draining_submit.is_alive())
        self.assertFalse(shutdown.is_alive())
        self.assertEqual(completed_audio, [b"first", b"second", b"third"])
        self.assertEqual(runtime.snapshot()["canceled"], 0)

    def test_rejected_live_segment_can_be_retried_while_accepted_work_drains(self):
        entered = threading.Event()
        release = threading.Event()
        completed_audio = []

        def handler(message):
            if message.audio_bytes == b"first":
                entered.set()
                release.wait(2)
            return True

        runtime = PipelineRuntime(
            (("stt", handler),),
            queue_capacity=1,
            enqueue_timeout_seconds=0.01,
            shutdown_timeout_seconds=2,
            on_complete=lambda message: completed_audio.append(message.audio_bytes),
        )
        runtime.start()
        runtime.submit(b"first")
        self.assertTrue(entered.wait(1))
        runtime.submit(b"second")
        with self.assertRaises(PipelineBackpressureError):
            runtime.submit(b"third")

        retry = threading.Thread(
            target=runtime.submit_for_drain,
            args=(b"third",),
        )
        retry.start()
        time.sleep(0.02)
        release.set()
        retry.join(2)
        runtime.shutdown(drain=True)

        self.assertEqual(completed_audio, [b"first", b"second", b"third"])
        metrics = runtime.snapshot()
        self.assertEqual(metrics["submitted"], 3)
        self.assertEqual(metrics["completed"], 3)
        self.assertEqual(metrics["canceled"], 0)
        self.assertEqual(metrics["overload_failures"], 1)

    def test_cancel_is_visible_and_shutdown_does_not_deadlock(self):
        entered = threading.Event()
        release = threading.Event()
        canceled = []

        def blocked_handler(_message):
            entered.set()
            release.wait(2)
            return True

        runtime = PipelineRuntime(
            (("stt", blocked_handler), ("playback", lambda _message: True)),
            queue_capacity=2,
            shutdown_timeout_seconds=2,
            on_cancel=lambda message: canceled.append(message.sequence_id),
        )
        runtime.start()
        runtime.submit(b"first")
        runtime.submit(b"second")
        self.assertTrue(entered.wait(1))

        shutdown = threading.Thread(
            target=runtime.shutdown,
            kwargs={"drain": False},
        )
        shutdown.start()
        time.sleep(0.02)
        release.set()
        shutdown.join(2)

        self.assertFalse(shutdown.is_alive())
        self.assertEqual(sorted(canceled), [1, 2])
        self.assertEqual(runtime.snapshot()["canceled"], 2)
        self.assertEqual(runtime.snapshot()["workers_alive"], [])

    def test_observer_failure_does_not_kill_worker_or_block_shutdown(self):
        observed = []

        def observer(message):
            observed.append(message.sequence_id)
            if message.sequence_id == 1:
                raise RuntimeError("observer failed")

        runtime = PipelineRuntime(
            (("stage", lambda _message: True),),
            on_complete=observer,
        )
        runtime.start()
        runtime.submit(b"first")
        runtime.submit(b"second")
        with self.assertLogs("src.pipeline_runtime", level="ERROR"):
            runtime.shutdown(drain=True)

        self.assertEqual(observed, [1, 2])
        self.assertEqual(runtime.snapshot()["completed"], 2)
        self.assertEqual(runtime.snapshot()["workers_alive"], [])


class CaptureQueueContinuityTests(unittest.TestCase):
    def test_full_capture_queue_preserves_oldest_and_counts_current_drop(self):
        audio_input = AudioInput.__new__(AudioInput)
        audio_input.dtype = "int16"
        audio_input.callback = None
        audio_input._queue = queue.Queue(maxsize=1)
        audio_input._dropped_chunks = 0
        oldest = np.array([[100]], dtype=np.int16)
        current = np.array([[200]], dtype=np.int16)

        audio_input._audio_callback(oldest, 1, None, None)
        with self.assertLogs("src.audio_in", level="ERROR"):
            audio_input._audio_callback(current, 1, None, None)

        self.assertEqual(audio_input.dropped_chunk_count(), 1)
        self.assertEqual(audio_input.queue_size(), 1)
        self.assertEqual(audio_input.read(timeout=0), oldest.tobytes())

    def test_opt_in_stereo_capture_is_mixed_to_mono(self):
        audio_input = AudioInput.__new__(AudioInput)
        audio_input.dtype = "int16"
        audio_input.mix_to_mono = True
        audio_input.callback = None
        audio_input._queue = queue.Queue(maxsize=1)
        audio_input._dropped_chunks = 0
        stereo = np.array([[1000, -1000], [1000, 0]], dtype=np.int16)

        audio_input._audio_callback(stereo, 2, None, None)

        mixed = np.frombuffer(audio_input.read(timeout=0), dtype=np.int16)
        np.testing.assert_array_equal(mixed, [0, 500])


class PlaybackCancellationTests(unittest.TestCase):
    def test_stop_playback_interrupts_sounddevice_convenience_playback(self):
        audio_output = AudioOutput.__new__(AudioOutput)

        with patch("src.audio_out.sd.stop") as stop:
            audio_output.stop_playback()

        stop.assert_called_once_with()


class TranslationPipelineWorkerTests(unittest.TestCase):
    def _minimal_pipeline(self, tmp_dir):
        components = PipelineComponents(
            audio_input=Mock(sample_rate=16000),
            audio_output=Mock(sample_rate=48000),
            vad=Mock(),
            stt=Mock(),
            translator=Mock(),
            tts=Mock(),
        )
        with patch("src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)):
            return TranslationPipeline(Mock(pipeline_config={}), components=components)

    def test_failure_and_cancel_callbacks_remove_temp_audio(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = self._minimal_pipeline(tmp_dir)
            failed_path = Path(tmp_dir) / "failed.wav"
            canceled_path = Path(tmp_dir) / "canceled.wav"
            failed_path.touch()
            canceled_path.touch()
            failed = PipelineMessage(1, b"audio", wav_path=failed_path)
            canceled = PipelineMessage(2, b"audio", wav_path=canceled_path)
            failed.error = "playback failed"
            canceled.error = "canceled before playback"

            pipeline._on_message_failure(failed)
            pipeline._on_message_cancel(canceled)

            self.assertFalse(failed_path.exists())
            self.assertFalse(canceled_path.exists())

    def test_cancel_stop_interrupts_active_playback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = self._minimal_pipeline(tmp_dir)

            pipeline.stop(cancel=True)

        pipeline.audio_output.stop_playback.assert_called_once_with()
        self.assertTrue(pipeline._stop_requested.is_set())
        self.assertTrue(pipeline._cancel_on_stop)

    def test_cancel_stop_survives_playback_interrupt_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = self._minimal_pipeline(tmp_dir)
            pipeline.audio_output.stop_playback.side_effect = RuntimeError("busy")

            with self.assertLogs("src.pipeline", level="WARNING"):
                pipeline.stop(cancel=True)

        self.assertTrue(pipeline._stop_requested.is_set())

    def test_outgoing_hallucination_does_not_reach_translation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pipeline = self._minimal_pipeline(tmp_dir)
            pipeline.stt.transcribe.return_value = "Altyazı M.K."

            with patch("src.pipeline.NOISE_REDUCE_AVAILABLE", False):
                self.assertFalse(pipeline.process_segment(b"\x00\x00"))

        pipeline.translator.translate.assert_not_called()

    def test_real_stage_adapters_preserve_playback_order_and_clean_temp_files(self):
        played = []
        audio_input = Mock(sample_rate=16000)
        audio_output = Mock(sample_rate=48000)

        def play_wav(path, blocking=True):
            played.append((path.read_text(encoding="utf-8"), blocking))
            return True

        audio_output.play_wav.side_effect = play_wav
        stt = Mock()
        stt.transcribe.side_effect = lambda audio, _rate: audio.decode("utf-8")
        translator = Mock()
        translator.translate.side_effect = lambda text: f"en-{text}"
        tts = Mock()
        tts.synthesize_to_wav.side_effect = (
            lambda text, path, sample_rate: (
                path.write_text(text, encoding="utf-8") is not None
            )
        )
        components = PipelineComponents(
            audio_input=audio_input,
            audio_output=audio_output,
            vad=Mock(),
            stt=stt,
            translator=translator,
            tts=tts,
        )
        config = Mock(pipeline_config={"stage_queue_capacity": 2})

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ), patch("src.pipeline.NOISE_REDUCE_AVAILABLE", False):
            pipeline = TranslationPipeline(config, components=components)
            pipeline._runtime.start()
            for text in (b"bir", b"iki", b"uc"):
                pipeline._runtime.submit(text)
            pipeline._runtime.shutdown(drain=True)
            self.assertEqual(list(Path(tmp_dir).iterdir()), [])

        self.assertEqual(
            played,
            [("en-bir", True), ("en-iki", True), ("en-uc", True)],
        )
        self.assertEqual(pipeline.runtime_metrics()["completed"], 3)

    def test_stop_requested_during_audio_start_is_not_lost(self):
        start_entered = threading.Event()
        allow_start = threading.Event()
        audio_input = Mock(sample_rate=16000)

        def start():
            start_entered.set()
            allow_start.wait(2)

        audio_input.start.side_effect = start
        audio_input.read.return_value = None
        components = PipelineComponents(
            audio_input=audio_input,
            audio_output=Mock(sample_rate=48000),
            vad=Mock(flush=Mock(return_value=None)),
            stt=Mock(),
            translator=Mock(),
            tts=Mock(),
        )
        config = Mock(pipeline_config={})

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ):
            pipeline = TranslationPipeline(config, components=components)
            live_thread = threading.Thread(target=pipeline.run_live)
            live_thread.start()
            self.assertTrue(start_entered.wait(1))
            pipeline.stop()
            allow_start.set()
            live_thread.join(2)

        self.assertFalse(live_thread.is_alive())
        audio_input.stop.assert_called_once_with()
        audio_input.read.assert_called_once_with(timeout=0)
        self.assertEqual(pipeline.runtime_metrics()["submitted"], 0)

    def test_live_ingress_overload_retries_current_segment_and_drains_accepted(self):
        stt_entered = threading.Event()
        release_stt = threading.Event()
        audio_input = Mock(sample_rate=16000)
        audio_input.read.side_effect = [b"one", b"two", b"three", None]
        audio_input.dropped_chunk_count.return_value = 0
        vad = Mock()
        vad.process_audio.side_effect = lambda chunk: chunk
        vad.flush.return_value = None
        stt = Mock()

        def transcribe(audio, _sample_rate):
            if audio == b"one":
                stt_entered.set()
                release_stt.wait(2)
            return audio.decode("utf-8")

        stt.transcribe.side_effect = transcribe
        translator = Mock()
        translator.translate.side_effect = lambda text: f"en-{text}"
        tts = Mock()
        tts.synthesize_to_wav.side_effect = (
            lambda text, path, sample_rate: (
                path.write_text(text, encoding="utf-8") is not None
            )
        )
        played = []
        audio_output = Mock(sample_rate=48000)
        audio_output.play_wav.side_effect = lambda path, blocking=True: (
            played.append(path.read_text(encoding="utf-8")) is None
        )
        components = PipelineComponents(
            audio_input=audio_input,
            audio_output=audio_output,
            vad=vad,
            stt=stt,
            translator=translator,
            tts=tts,
        )
        config = Mock(
            pipeline_config={
                "stage_queue_capacity": 1,
                "enqueue_timeout_seconds": 0.01,
                "shutdown_timeout_seconds": 2,
            }
        )
        errors = []

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ), patch("src.pipeline.NOISE_REDUCE_AVAILABLE", False):
            pipeline = TranslationPipeline(config, components=components)

            def run_live():
                try:
                    pipeline.run_live()
                except Exception as exc:
                    errors.append(exc)

            live_thread = threading.Thread(target=run_live)
            live_thread.start()
            self.assertTrue(stt_entered.wait(1))
            time.sleep(0.03)
            release_stt.set()
            live_thread.join(3)

        self.assertFalse(live_thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PipelineBackpressureError)
        self.assertEqual(played, ["en-one", "en-two", "en-three"])
        metrics = pipeline.runtime_metrics()
        self.assertEqual(metrics["submitted"], 3)
        self.assertEqual(metrics["completed"], 3)
        self.assertEqual(metrics["canceled"], 0)
        self.assertEqual(metrics["overload_failures"], 1)


if __name__ == "__main__":
    unittest.main()
