# Whisper tiny.en on the UNO Q

**Date:** 2026-10-29, America/Los_Angeles

**Status:** Isolated experiment implemented. Fixed-file and paced-replay
measurements completed; live microphone recognition has not passed acceptance.

The user requested a small on-device English speech-recognition experiment,
following the [benchmark design](../design-spec/2026-10-29-isolated-whisper-tiny-benchmark.md).
The [harness](../../projects/whisper-tiny-benchmark/README.md) lives separately at
`/home/arduino/torque/projects/whisper-tiny-benchmark/`. It uses a private binary
Python environment and the installed Torque Python only for orchestration and
the existing microphone API. No runtime release, service configuration, MCU
sketch, Arduino app or boot-default change is part of this experiment.

## Reproducible inputs and setup

- UNO Q: four Cortex-A53 CPU cores, maximum 2.016 GHz, 4 GB RAM variant;
  CPython 3.13.5, glibc 2.41. Torque release `0.2.0-9ed93a142a1d`, controller
  0.4.0/protocol 1.3, MCU boot `1295313560`.
- CPU-only `pywhispercpp==1.5.1`, with NEON, ARM FMA, OpenMP and repacking
  reported by the backend. The published binding tag identifies upstream
  `whisper.cpp` submodule `f24588a272ae8e23280d9c220536437164e6ed28`.
  [Pinned dependency wheels](../../projects/whisper-tiny-benchmark/requirements.lock)
  include all eleven exact versions and hashes. The wheel hash, rather than a
  guessed equivalence to another backend/build, identifies the executable used.
- Original Tiny English GGML weights: 77,704,715 bytes, model revision
  `5359861c739e955e79d9a303bcbc70fb988958b1`, SHA-256
  `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`.
  See the [model lock](../../projects/whisper-tiny-benchmark/model-lock.json).
- Six complete LibriSpeech test-clean recordings, two speakers, with durations
  3.505, 5.850, 13.160, 6.285, 3.855 and 13.585 seconds. IDs, reference text,
  source/converted hashes, conversion recipe and CC BY 4.0 attribution are in
  [the fixture manifest](../../projects/whisper-tiny-benchmark/fixtures.json).
  Selection preceded recognition. Samples were prepared on the Mac, without
  downloading the full corpus onto the UNO Q. A selected fixture served as the
  compatibility smoke test instead of downloading an additional JFK recording.

The board lacked `ensurepip` and a compiler toolchain. An empty private venv was
created, and the installed runtime's existing pip targeted that venv through its
`--python` option. Only binary wheels were installed there; no apt operation,
global Python installation or active-release source edit was needed. The project
initially occupied approximately 164 MB, including its single model and fixtures.

## File inference

Both configurations use English, greedy best-of-one decoding, temperature zero,
no temperature fallback, no prompt hints, no text-context reuse and CPU-only
execution. The model remains loaded for three warm repetitions of each clip.
Process startup/model load and the first inference are recorded separately.

The retained repeat sweep measured median warm decode times of 9.912 seconds
with two threads and 5.229 seconds with four. The aggregate RTF was 1.321 and
0.702 respectively. Short 3.5–3.9-second commands still took approximately five
seconds with four threads; 13-second recordings took approximately six seconds.
Warm timing is the complete transcription call, not an encoder-only benchmark.

The original 7.4% WER was invalidated during the GPU follow-up: the Python
harness concatenated stripped segment texts without spaces, creating false word
errors such as `partitionof`. Historical raw records and latency remain intact.
The worker now preserves word boundaries; a new six-clip accuracy pass with each
thread setting (`20261030T060930-accuracy-correction`) found **2/136 word errors,
1.5%**, matching the native CPU control. This is a separate accuracy recheck,
not a rescore of unrecoverable historical segment boundaries. The old replay
WER is also marked invalid; its endpoint/timing records remain usable. See the
[follow-up journal](2026-10-29-whisper-vulkan-gpu-benchmark.md).

Scoring uses identically normalized reference
and hypothesis text. The corrected pass had four exact utterances and two
utterances with one word error each. Repetitions are not additional independent speech samples, and this
small result does not establish general dictation accuracy or performance on
the user's accent, voice, room or microphone.

Worker peak RSS was approximately 199–200 MiB. Model load was about 0.25 seconds;
process/import/model-to-ready was about 1.3 seconds. These are fresh-process
results with ordinary filesystem caching, not forced cold-storage measurements.
The silence control returned the literal `[BLANK_AUDIO]` marker, not a command.

Torque's persistent-connection status IPC remained ready: baseline median about
2.8 ms, under-load medians about 1.7–2.0 ms, and sampled maxima below 8 ms in the
retained sweep. This checks Linux daemon response separately from MCU playback.

An initial retention rule removed the first raw file-run directory during later
microphone retries. Its generated summary was already preserved. The harness
was corrected to pin fixed-file/replay baselines, and the file sweep was repeated
with complete raw measurements retained in `20261030T031529-files`. The original
summary (9.958/5.246-second medians) and the retained repeat agree closely. Completed
older unpinned results can still be pruned within the three-run/20 MiB budget;
pinned or unfinished data filling the budget causes a refusal rather than loss.

## Endpointing and microphone observations

Paced fixture replay adds trailing silence and uses the same WebRTC VAD policy
as live capture. The initial short recordings measured about 5.7–5.9 seconds
from the last VAD-positive sample to the final transcript. This includes the
700 ms silence policy. There are no independent human speech-end annotations:
file-end and VAD-end timestamps are explicitly labelled proxies, not ground
truth. Model segment callbacks on short phrases arrived near final output;
they did not provide useful early partial words in this configuration.

The first three live trials used terminal/chat cues. The user reported missing
some windows because the cues moved too quickly. Those trial scores therefore
cannot be treated as controlled microphone recognition accuracy. A resampler
burst also exposed an endpoint bug: the detector could keep updating its last
speech boundary after an earlier endpoint inside that burst. The correction
freezes at the first endpoint and trims the inference buffer there. A synthetic
regression test covers later speech in the same burst.

At the user's request, `--guide-matrix` adds a physical 3-2-1 countdown, hollow
circle for speaking, three dots while transcribing and a completion check.
Guided trials run one phrase at a time, allow 30 seconds after the cue and keep
capture finite at 40 seconds. They temporarily own the matrix, then close the
Board connection to restore normal status. A check means processing finished,
not that the recognized phrase was correct.

The first guided trial returned `(upbeat music)` instead of the prompted phrase.
It reached the 30-second limit without a reliable endpoint. This is failed live
speech recognition, not proof that music was actually present. The room/input
conditions and correct cue participation need confirmation. Small amounts of
clipping were observed in some live trials; the first guided trial had 20
samples at the clipping threshold. Signal amplitude alone does not prove usable
voice quality. The harness now also separates DC mean, total RMS, AC RMS and
VAD-positive duration for any subsequent diagnostic.

An additional offline format check converted the known 3.505-second fixture to
48 kHz S32_LE, then sent it through the same resampler and endpointing code as
live capture. It produced the exact eight reference words. This establishes a
working software format path, not that the physical microphone signal is clean.
That diagnostic overlapped the ARM unit suite, so its decode time is explicitly
excluded from performance comparisons.

All completed microphone trials reported exact restoration of the nine touched
mixer controls. Microphone PCM stayed in memory; recognized text was displayed
in the tool/terminal, not saved in metric files. Prompt IDs, error counts,
amplitude/clipping and timings were saved. Recognized phrases never executed
board commands or agent turns. No cloud inference or voice upload was used.

## Verification and retained artifacts

The final complete repository suite passed 331 tests on the Mac (two optional
skips) and UNO Q (four optional/compiler skips). Five private-environment DSP
checks passed, covering sample counts, anti-alias rejection, silence endpointing,
buffer bounds, endpoint freezing inside a burst, and separate DC/AC statistics.
The repository checks also cover scoring, invalid inputs, process cleanup,
matrix-cue dimensions and protected result retention.

The final cleanup receipt confirms that capture is closed, audio/program leases
are free and the matrix has no foreground owner. Readback observed five distinct
matching Heart Pulse frames. Runtime release and daemon epoch, firmware boot,
service-unit hash, settings hash and conversation were unchanged. The Arduino
boot default still identifies `/var/lib/torque/device/uno-q/controller`. No flash,
controller restart or Torque service restart was performed. This is software
readback; a person's observation of the LEDs is separate.

Raw retained phase directories on UNO Q are `20261030T031529-files`,
`20261030T030038-replay` and `20261030T031059-mic` under the project's `results/`.
UTC run IDs fall on 2026-10-30; the local journal date is 2026-10-29. Local copies
of these small metric files are retained beside the harness, while fixtures,
models, private environments and raw results are ignored by Git. The initial
mistimed microphone metrics were also copied locally before pruning, rather
than being folded into accepted recognition accuracy.

See the [generated measurements](../../projects/whisper-tiny-benchmark/report.md).

After the experiments were complete, the user requested removal of both Whisper
projects from the UNO Q. The local sources/results and an off-board archive
remain; see the [removal record](2026-10-29-whisper-vulkan-gpu-benchmark.md#subsequent-user-requested-removal-from-the-board).
The board also retains `cleanup-acceptance.json`, dependency-install metadata,
test logs and the public-audio-only `scratch/format-check.json`. No microphone
audio file exists. A further live capture waits for the user's confirmation of
room conditions and cue participation.

## Outcome

Four threads are preferable to two for this tested CPU build. The Tiny English
model fits the available memory, but approximately five seconds of warm decoding
already exceeds the one-second post-speech target before adding silence,
transport and capture-cleanup time. Aggregate faster-than-real-time processing
of longer recordings does not make short command response instantaneous.

Keep this as a measured experiment. Live microphone recognition remains
unaccepted, and reliable human end-to-final latency is not established. A small
streaming recognizer or a separately measured optimized build is a next candidate;
the existing SDK has not acquired a production speech-recognition feature.
