---
name: pipeline-refactor
description: Incrementally evolve the synchronous live-translation pipeline into bounded queues and workers; do not use it for a one-shot rewrite or backend replacement.
---

# Pipeline Refactor

The conceptual V2 direction is:

```text
Audio Capture
      |
Audio / Segment Queue
      |
STT Worker
      |
Translation Queue
      |
Translation Worker
      |
TTS Queue
      |
TTS Worker
      |
Playback Queue
```

This is a direction, not permission to rewrite the pipeline in one change.

## Sequencing

1. Introduce and validate interfaces or stage boundaries.
2. Add bounded queues with documented capacity and backpressure.
3. Move one stage at a time into a worker.
4. Add streaming only where measurements justify it.

## Invariants

- Preserve ordered output.
- Define overload and backpressure behavior explicitly; never solve overload by silently deleting speech.
- Support clean startup, shutdown, draining, and cancellation.
- Contain exceptions so workers do not deadlock or strand queue items.
- Instrument queue depth and per-stage/end-to-end latency.
- Test queue saturation, stage failure, ordering, and shutdown behavior.
- Review shared state for races and blocking calls.
- Keep each phase independently reversible and preserve existing platform behavior.
