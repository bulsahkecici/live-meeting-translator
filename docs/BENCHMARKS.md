# Benchmarks

This document contains measured local evidence plus templates for later phases.
Phase 4 STT results are from real, local human speech and are not extrapolated
beyond the stated corpus and machine.

## Measurement rules

- Record hardware, OS, Python version, configuration, and warm/cold state with each run.
- Use representative Turkish meeting speech and preserve the same samples across backend comparisons where permitted.
- Measure each stage independently and end to end with a monotonic clock.
- Report failures, queue overflow, and dropped or skipped audio; do not exclude them from results.
- Keep raw benchmark artifacts out of Git when they contain audio, transcripts, secrets, or generated media.

## STT

### Phase 4 method

- Date: 2026-09-22.
- Host: MacBook Pro `Mac17,6`, Apple M5 Max (18 cores), 36 GB memory; macOS
  26.6.2 arm64; Python 3.11.16.
- Corpus: ten prompted utterances from one Turkish speaker, 69.000 seconds total,
  16 kHz mono PCM16. The manifest is tracked at
  `benchmarks/stt_manifest.json`; recordings stay local under the ignored
  `benchmarks/local_stt_audio/` directory and were never uploaded.
- Every model received the identical WAV set. WAVs were decoded to PCM bytes and
  passed as in-memory NumPy waveforms; no temporary inference WAV was created.
- Models were downloaded before timing. Every final run used a fresh process and
  `HF_HUB_OFFLINE=1`. Model-load time excludes backend/module imports. One first
  utterance warm-up inference was recorded separately and excluded from corpus
  totals. No backend VAD was enabled; inputs were already manually segmented.
- Faster Whisper settings: `small`, CPU, int8, Turkish, `beam_size=1`,
  `vad_filter=False`.
- MLX settings: Metal, float16, Turkish, temperature 0, greedy decoding. MLX
  Whisper 0.4.3 does not implement beam search, so its search is not bit-for-bit
  equivalent to Faster Whisper.
- Normalization: Unicode NFC; Turkish-aware `I → ı` and `İ → i` before lowercase;
  Unicode punctuation replaced by spaces; repeated whitespace collapsed.
  `ş, ğ, ı, ö, ü, ç` are preserved as meaningful characters. CER includes the
  single normalized spaces. Corpus WER/CER aggregate edit counts rather than
  averaging utterance rates.

### Aggregate results

| Backend | Exact model | Device/dtype | Model load | Warm-up (excluded) | Audio | Inference | RTF | WER | CER | Peak RSS |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Faster Whisper 1.2.1 | `small` | CPU/int8 | 0.2968 s | 0.8154 s | 69.000 s | 7.9434 s | 0.1151 | 0.4500 | 0.1675 | 1.127 GB |
| MLX Whisper 0.4.3 | `mlx-community/whisper-small-mlx` | Metal/float16 | 0.1203 s | 0.1396 s | 69.000 s | 0.6648 s | 0.0096 | 0.4500 | 0.1658 | 0.894 GB |
| MLX Whisper 0.4.3 | `mlx-community/whisper-large-v3-turbo` | Metal/float16 | 0.0616 s | 0.2030 s | 69.000 s | 1.2207 s | 0.0177 | 0.3000 | 0.1215 | 1.855 GB |

The backend-parity comparison is Faster Whisper `small` versus MLX Whisper
`small`, not Turbo. MLX small completed inference about 11.9 times faster while
matching WER and differing by only one aggregate character error. The practical
Mac comparison is MLX small versus MLX large-v3-turbo. Turbo used about 1.84
times the inference time but reduced word errors from 36/80 to 24/80 and
character errors from 101/609 to 74/609. Turbo remained about 56.5 times faster
than real time on this corpus. These figures support Turbo for the explicit
primary-Mac deployment profile; the factory's compatibility default remains
Faster Whisper for selector-free and Windows configurations.

### Per-utterance inference time

| ID | Audio | Faster small | MLX small | MLX large-v3-turbo |
| --- | ---: | ---: | ---: | ---: |
| `tr_01_conversation` | 6.000 s | 0.785140 s | 0.061082 s | 0.118728 s |
| `tr_02_live_translation` | 6.000 s | 0.753671 s | 0.052218 s | 0.114280 s |
| `tr_03_numbers` | 7.000 s | 0.780160 s | 0.059096 s | 0.118274 s |
| `tr_04_date` | 7.000 s | 0.783436 s | 0.062873 s | 0.117365 s |
| `tr_05_tunnel` | 7.000 s | 0.803341 s | 0.071893 s | 0.129624 s |
| `tr_06_concrete` | 7.000 s | 0.822086 s | 0.078067 s | 0.124958 s |
| `tr_07_apple_silicon` | 7.000 s | 0.798549 s | 0.068494 s | 0.121305 s |
| `tr_08_cuda_metal` | 8.000 s | 0.810374 s | 0.071908 s | 0.126765 s |
| `tr_09_short` | 4.000 s | 0.716300 s | 0.039127 s | 0.101852 s |
| `tr_10_long` | 10.000 s | 0.890381 s | 0.100036 s | 0.147586 s |

### Transcripts

| ID | Reference | Faster small | MLX small | MLX large-v3-turbo |
| --- | --- | --- | --- | --- |
| `tr_01_conversation` | Bugünkü toplantıda yeni proje takvimini konuşacağız. | Bugün ki toplantıda yeni proje takdimini konuşacağız. | Bugün ki toplantıda yeni proje takdimini konuşacağız. | Bugünkü toplantıda yeni proje takvimini konuşacağız. |
| `tr_02_live_translation` | Mikrofonumu açıp gerçek zamanlı çeviriyi deniyorum. | mikrofonumu açık gerçek zamanı çeviri deniyorum | mikrofonumu açık gerçek zamanı çeviri deniyorum | Bu mikrofonumu açıp gerçek zaman çeviri deniyorum |
| `tr_03_numbers` | Toplam mesafe on iki virgül beş kilometre olarak ölçüldü. | Toplam mesafe 12,5 kilometre olarak ölçüldü. | Toplam mesafe 12,5 km olarak ölçüldü. | Toplam mesafe 12,5 km olarak ölçüldü. |
| `tr_04_date` | Toplantı yirmi üç Eylül iki bin yirmi altı tarihinde yapılacak. | Toplantı 23 Eylül 2026 tarlında yapılacak. | Toplantı 23.Elil 2026 tarlında yapılacak. | Bu toplantı 23 Eylül 2026 tarihinde yapılacak |
| `tr_05_tunnel` | NATM yöntemiyle açılan tünelde güvenlik kontrolü tamamlandı. | Not Mühendim ile açılan dünya güvenlik kontrolü tamamlandı. | Not Mühendim ile açılan tünende güvenlik kontrolü tamamlandı. | Natm yöntemiyle açılan tünelde güvenlik kontrolü tamamlandı. |
| `tr_06_concrete` | Betonarme taşıyıcı sistemin hesapları yeniden gözden geçirildi. | Beton Ermet Taşıcı sisteminin hesapları yeniden gözden getirildi. | Beton Ermet Taşıcı sistemin hesapları yeniden gözden getirildi. | betonelme taşıyıcı sistemin hesapları yeniden gözden getirildi |
| `tr_07_apple_silicon` | Yapay zekâ modeli Apple Silicon üzerinde yerel olarak çalışıyor. | Yapay zekalı modeli Apple silikon üzerinde yerle olarak çalışıyor. | Yapay zekalı modeli Apple silikon üzerinde yerle olarak çalışıyor. | yapay zekan modeli Apple silikon üzerine yerel olarak çalışıyor |
| `tr_08_cuda_metal` | CUDA desteği Windows bilgisayarda, Metal desteği ise Mac üzerinde kullanılacak. | Kürda desteği Windows Mixer'da metal desteği istemek üzerinde kullanılacak. | Kürda desteği Windows Mixer'da metal desteği istemek üzerinde kullanılacak. | bu küda desteği Windows bilgisayarda metal desteği istemek üzerinde kullanılacak |
| `tr_09_short` | Sesim net geliyor mu? | Sesim net geliyor mu? | Sesim net geliyor mu? | Sesim net geliyor mu |
| `tr_10_long` | Ekip, toplantı sırasında mikrofon gecikmesini ölçüp gerçek zamanlı çeviri sonuçlarını dikkatle karşılaştıracak. | Ekip toplantı sırasında mikrofon gecikmesini ölçüp gerçek zamanı çeviri sonuçtan dikkatle karşılaştıracak. | ekip toplantı sırasında mikrofon gecikmesini ölçüp gerçek zamanı çeviri sonuçlarını dikkatle karşılaştıracak. | Ekip toplantı sırasında mikrofon gecikmesini ölçüp gerçek zamanlı çeviri sonuçlarını dikkatle karşılaştıracak. |

### Limits and artifacts

This is a single-speaker, single-run corpus with fixed post-speech silence, not a
population estimate or sustained-load test. RTF uses full WAV duration. Numeric
and abbreviation formatting is not semantically normalized, so outputs such as
`12,5` versus `on iki virgül beş` count as errors. Model-load measurements use a
warm filesystem cache and are not cold application-start timings. The local JSON
reports contain the machine-readable raw measurements but remain ignored. Model
snapshots are outside the repository in the normal Hugging Face cache; observed
logical snapshot sizes (`du -shL`) were approximately 927 MB for Faster small,
918 MB for MLX small, and 3.0 GB for MLX Turbo. Full Turbo was already far below
RTF 1 and its approximately 1.855 GB peak process RSS was acceptable on this
36 GB machine, so the optional 4-bit model was not downloaded.

## Translation

| Backend | Model/service | Input chars | Latency | Context size | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| | | | | | |

## TTS

| Backend | Model/voice | Text length | Time-to-first-audio | Total synthesis time | Audio duration | RTF | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| | | | | | | | |

## End-to-end

Phase 5 adds monotonic per-stage and segmentation-to-playback timing plus queue
depth/high-water and continuity counters to the live runtime. Deterministic fake
stage tests validate concurrency, ordering, bounded saturation, failure
containment, and shutdown; they are correctness evidence, not performance
measurements. A real DeepL/Edge/SAPI meeting run has not yet been measured, so no
latency row is added here.

| Segment duration | STT | Translation | TTS first audio | TTS total | Playback start | End-to-end perceived latency | Dropped audio | Notes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| | | | | | | | | |

## Audio routing

These measurements cover only the raw Phase 2 microphone-to-BlackHole path. The
timestamp values are PortAudio callback scheduling latency, not translation or
human-perceived end-to-end latency.

| Date | Path | Format | Active duration | Queue high-water/final | Overflows | Underflows | Dropped chunks | Source RMS/peak | Loopback RMS/peak | Capture-to-playback timestamps | Notes |
| --- | --- | --- | ---: | --- | --- | --- | ---: | --- | --- | --- | --- |
| 2026-09-21 | MacBook Pro Mikrofonu -> BlackHole 2ch output -> BlackHole 2ch input | 48 kHz, float32, mono -> stereo, 480-frame blocks | 10.009 s | 6/0 blocks | input 0; loopback input 0; queue 0 | output 0; active queue 0 | 0 | 0.00371006/0.02991113 | 0.00367019/0.02991113 | mean 81.033 ms; min 81.023 ms; max 81.043 ms; n=1,007 | Raw bounded routing PASS; 483,360 captured/submitted frames; post-output loopback RMS/peak ratios 0.989252/1.000000; no recording, speakers, system-default changes, STT, translation, or TTS |

### Incoming subtitle acceptance (2026-09-22)

A fixed local macOS `say` utterance, “Hello, this is the incoming English
channel test,” was played through `Zoom Incoming Monitor`. The Multi-Output
device sent it to the MacBook speakers and BlackHole 16ch; the application
captured BlackHole 16ch at 48 kHz stereo, mixed it to mono in memory, and ran
Faster Whisper small followed by DeepL EN-to-TR. STT returned the exact English
sentence. Translation returned `Merhaba, bu, gelen İngilizce kanalının test
yayınıdır.` STT took 0.779 s, translation 0.753 s, and segment completion took
1.532 s. One segment completed with zero failures, overloads, cancellations, or
capture drops; both queues drained and both workers stopped. Temporary test
audio was deleted. This is a routing/integration acceptance, not a quality
benchmark or a real Zoom call. The final post-mix repeat again produced the
exact English transcript and the same Turkish translation with 1.326 s total
segment completion.
