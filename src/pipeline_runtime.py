"""Bounded, ordered worker runtime for live translation stages."""
from dataclasses import dataclass, field
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Callable, Dict, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_STOP = object()


class PipelineBackpressureError(RuntimeError):
    """Raised when the live pipeline cannot accept speech without dropping it."""


@dataclass
class PipelineMessage:
    """One ordered speech segment and its stage outputs."""

    sequence_id: int
    audio_bytes: bytes
    created_at: float = field(default_factory=time.monotonic)
    source_text: Optional[str] = None
    translated_text: Optional[str] = None
    wav_path: Optional[Path] = None
    stage_seconds: Dict[str, float] = field(default_factory=dict)
    error: Optional[str] = None
    terminal: bool = False


class PipelineRuntime:
    """Run one worker per stage over bounded FIFO queues."""

    def __init__(
        self,
        stages: Sequence[Tuple[str, Callable[[PipelineMessage], bool]]],
        *,
        queue_capacity: int = 4,
        enqueue_timeout_seconds: float = 2.0,
        shutdown_timeout_seconds: float = 30.0,
        on_complete: Optional[Callable[[PipelineMessage], None]] = None,
        on_failure: Optional[Callable[[PipelineMessage], None]] = None,
        on_cancel: Optional[Callable[[PipelineMessage], None]] = None,
    ):
        if not stages:
            raise ValueError("at least one pipeline stage is required")
        if queue_capacity < 1:
            raise ValueError("pipeline queue capacity must be at least one")
        if enqueue_timeout_seconds <= 0 or shutdown_timeout_seconds <= 0:
            raise ValueError("pipeline timeouts must be greater than zero")

        self._stages = tuple(stages)
        self._queues = {
            name: queue.Queue(maxsize=queue_capacity) for name, _handler in stages
        }
        self._enqueue_timeout = enqueue_timeout_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._on_complete = on_complete
        self._on_failure = on_failure
        self._on_cancel = on_cancel
        self._threads = []
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._started = False
        self._accepting = False
        self._closed = False
        self._next_sequence = 1
        self._metrics = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "canceled": 0,
            "overload_failures": 0,
            "queue_high_water": {name: 0 for name, _handler in stages},
            "stage_total_seconds": {name: 0.0 for name, _handler in stages},
            "stage_completed": {name: 0 for name, _handler in stages},
            "last_completed_sequence": None,
            "last_end_to_end_seconds": None,
        }

    def start(self) -> None:
        """Start each stage worker exactly once."""
        with self._lifecycle_lock:
            if self._started:
                raise RuntimeError("pipeline workers have already been started")
            self._started = True
            self._accepting = True
            for index, (name, handler) in enumerate(self._stages):
                output_queue = None
                if index + 1 < len(self._stages):
                    output_queue = self._queues[self._stages[index + 1][0]]
                thread = threading.Thread(
                    target=self._worker_loop,
                    args=(name, handler, self._queues[name], output_queue),
                    name=f"pipeline-{name}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)

    def submit(self, audio_bytes: bytes) -> PipelineMessage:
        """Submit one segment, failing visibly instead of evicting queued speech."""
        return self._submit(audio_bytes, self._enqueue_timeout, live=True)

    def shutdown_deadline(self) -> float:
        """Return a monotonic deadline shared by drain submission and joins."""
        return time.monotonic() + self._shutdown_timeout

    def submit_for_drain(
        self,
        audio_bytes: bytes,
        *,
        deadline: Optional[float] = None,
    ) -> PipelineMessage:
        """Submit captured speech using the overall shutdown timeout."""
        timeout = self._shutdown_timeout
        if deadline is not None:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise PipelineBackpressureError(
                    "pipeline shutdown deadline expired before captured speech "
                    "could be submitted"
                )
        return self._submit(audio_bytes, timeout, live=False)

    def _submit(
        self,
        audio_bytes: bytes,
        timeout_seconds: float,
        *,
        live: bool,
    ) -> PipelineMessage:
        with self._lifecycle_lock:
            if not self._started or not self._accepting:
                raise RuntimeError("pipeline workers are not accepting segments")
            sequence_id = self._next_sequence
            self._next_sequence += 1
            message = PipelineMessage(
                sequence_id=sequence_id,
                audio_bytes=audio_bytes,
            )
            first_name = self._stages[0][0]
            first_queue = self._queues[first_name]
            try:
                first_queue.put(message, timeout=timeout_seconds)
            except queue.Full as exc:
                if live:
                    with self._lock:
                        self._metrics["overload_failures"] += 1
                raise PipelineBackpressureError(
                    f"{first_name} queue remained full for "
                    f"{timeout_seconds:.3f}s; capture is stopping rather "
                    "than deleting queued speech"
                ) from exc
            with self._lock:
                self._metrics["submitted"] += 1
            self._observe_depth(first_name)
            return message

    def shutdown(
        self,
        *,
        drain: bool = True,
        deadline: Optional[float] = None,
    ) -> None:
        """Stop accepting work, then drain or visibly cancel queued messages."""
        deadline = deadline or self.shutdown_deadline()
        with self._lifecycle_lock:
            if not self._started or self._closed:
                return
            self._accepting = False
            if not drain:
                self._cancel_event.set()
            first_queue = self._queues[self._stages[0][0]]
            self._put_control(first_queue, _STOP, deadline)
            for thread in self._threads:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                thread.join(remaining)
            alive = [thread.name for thread in self._threads if thread.is_alive()]
            if alive:
                raise RuntimeError(
                    "pipeline worker shutdown timed out: " + ", ".join(alive)
                )
            self._closed = True

    def snapshot(self) -> dict:
        """Return a thread-safe metrics snapshot including current queue depths."""
        with self._lock:
            snapshot = {
                key: (value.copy() if isinstance(value, dict) else value)
                for key, value in self._metrics.items()
            }
        snapshot["queue_depth"] = {
            name: stage_queue.qsize()
            for name, stage_queue in self._queues.items()
        }
        snapshot["workers_alive"] = [
            thread.name for thread in self._threads if thread.is_alive()
        ]
        return snapshot

    def _worker_loop(self, name, handler, input_queue, output_queue) -> None:
        while True:
            message = input_queue.get()
            try:
                if message is _STOP:
                    if output_queue is not None:
                        self._put_control(output_queue, _STOP, None)
                    return
                if self._cancel_event.is_set():
                    self._cancel_message(message, name)
                    continue

                started = time.perf_counter()
                try:
                    succeeded = handler(message)
                except Exception as exc:
                    logger.error(
                        "Pipeline stage %s failed for segment %s: %s",
                        name,
                        message.sequence_id,
                        exc,
                        exc_info=True,
                    )
                    message.error = f"{name}: {exc}"
                    succeeded = False
                elapsed = time.perf_counter() - started
                message.stage_seconds[name] = elapsed
                with self._lock:
                    self._metrics["stage_total_seconds"][name] += elapsed
                    self._metrics["stage_completed"][name] += 1

                if not succeeded:
                    if not message.error:
                        message.error = f"{name} returned no result"
                    self._fail_message(message)
                    continue
                if output_queue is None:
                    self._complete_message(message)
                elif not self._forward(name, output_queue, message):
                    self._cancel_message(message, name)
            finally:
                input_queue.task_done()

    def _forward(self, name, output_queue, message) -> bool:
        next_name = self._next_stage_name(name)
        while not self._cancel_event.is_set():
            try:
                output_queue.put(message, timeout=0.1)
                self._observe_depth(next_name)
                return True
            except queue.Full:
                continue
        return False

    def _put_control(self, target_queue, value, deadline) -> None:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError("timed out while signaling pipeline shutdown")
            try:
                target_queue.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def _next_stage_name(self, current_name: str) -> str:
        names = [name for name, _handler in self._stages]
        return names[names.index(current_name) + 1]

    def _observe_depth(self, name: str) -> None:
        depth = self._queues[name].qsize()
        with self._lock:
            self._metrics["queue_high_water"][name] = max(
                self._metrics["queue_high_water"][name], depth
            )
        logger.debug("Pipeline queue %s depth=%s", name, depth)

    def _complete_message(self, message: PipelineMessage) -> None:
        if not self._mark_terminal(message):
            return
        elapsed = time.monotonic() - message.created_at
        with self._lock:
            self._metrics["completed"] += 1
            self._metrics["last_completed_sequence"] = message.sequence_id
            self._metrics["last_end_to_end_seconds"] = elapsed
        self._invoke_callback("complete", self._on_complete, message)

    def _fail_message(self, message: PipelineMessage) -> None:
        if not self._mark_terminal(message):
            return
        with self._lock:
            self._metrics["failed"] += 1
        self._invoke_callback("failure", self._on_failure, message)

    def _cancel_message(self, message: PipelineMessage, stage_name: str) -> None:
        if not self._mark_terminal(message):
            return
        message.error = f"canceled before {stage_name} completed"
        with self._lock:
            self._metrics["canceled"] += 1
        self._invoke_callback("cancel", self._on_cancel, message)

    def _invoke_callback(self, name, callback, message) -> None:
        if callback is None:
            return
        try:
            callback(message)
        except Exception as exc:
            logger.error(
                "Pipeline %s callback failed for segment %s: %s",
                name,
                message.sequence_id,
                exc,
                exc_info=True,
            )

    def _mark_terminal(self, message: PipelineMessage) -> bool:
        with self._lock:
            if message.terminal:
                return False
            message.terminal = True
            return True
