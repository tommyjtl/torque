# ncnn speech experiment

**Archived reference.** The GPU configuration failed the latency target and is
closed for now. CPU Zipformer is the selected next direction; the small
[CPU project](../zipformer-cpu/README.md) is its retained entrypoint. GPU source,
measurements and logs are preserved off-board for evidence. The old on-board
experiment directory and build tools have been removed after CPU preservation
and verification; this local source folder remains as an archived reference.

An isolated Linux ARM64 experiment on the UNO Q's actual Adreno 702. This
project preserves the existing Moonshine environment and resident MCU controller.
Sources, tools and models are privately staged, with a 2 GiB project budget.
Source/package/model hashes and build flags are recorded. No OS installation,
driver change, Arduino app start/stop or firmware upload is involved.

The initial gate performs a vector addition and three matrix multiplications
through explicit Vulkan tensors and queue submission, then compares downloaded
results with CPU references. Hardware enumeration or a model GPU option alone
does not count. A passed gate is required before `prepare_model.py` stages the
small English streaming Zipformer model and copies the six hashed Moonshine
fixtures. This is a new recognizer, not an optimization of Moonshine weights.

On the board, after the reviewed sources and private toolchain are staged:

```bash
python3 build.py
torque run ~/torque/projects/ncnn-speech-benchmark/runner.py probe
python3 prepare_model.py
python3 apply_profile.py
python3 build.py torque-ncnn-speech
torque run ~/torque/projects/ncnn-speech-benchmark/runner.py cpu --bulk --first-clip
torque run ~/torque/projects/ncnn-speech-benchmark/runner.py gpu --bulk --profile --first-clip
```

After those gates pass, `python3 launch.py cpu --repeats 3` starts a finite paced
sweep independently of SSH. Wait for its passed `result.json` and process exit
before `python3 launch.py gpu --repeats 3`. The latest launch PID/log are under
`scratch/latest-job.json`; results and IPC samples are under `results/`.
`--bulk` is a diagnostic throughput/correctness mode, not speech-end latency.
Normal paced runs disable per-layer profiling; the GPU run references the
successful hardware-timestamp calibration of that same executable.

Observed paced results: CPU median **0.387 s** after file end (18/18 below one
second), GPU hybrid median **6.457 s** (0/18). Both had **4/136 word errors** and
identical normalized transcripts on all paired trials. This conservative FP32
GPU configuration is functional but slower. The fast 0.3-second endpoint rule
can split a longer utterance into multiple segments; these were joined for
scoring and last-segment timing. Whole-turn detection and live microphone
latency remain unvalidated. See [measurements](report.md).

The native probe has parent-death handling, a finite deadline and core dumps
disabled. The runner passes Torque program/release leases, preserves status
display ownership and records MCU boot/runtime continuity. Raw logs/results,
build artifacts, downloaded tools and models are ignored by Git; reference
source and small manifests remain reviewable. Model input files are public
LibriSpeech recordings; no microphone is opened by the initial test.
