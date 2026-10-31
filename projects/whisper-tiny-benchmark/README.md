# Whisper tiny.en experiment

A finite CPU benchmark in a separate UNO Q project. It does not install a
recognizer into Torque, execute recognized commands, change firmware or restart
services. Fixed clips are LibriSpeech test-clean utterances, CC BY 4.0; attribution
and source/converted hashes are in `fixtures.json`.

On the UNO Q, the installed Torque Python runs `runner.py`; `.venv/bin/python`
runs the inference worker with its private binary dependencies. The original
Tiny English weights are pinned in `model-lock.json`. No GPU backend is used.

From the board shell:

```bash
torque run ~/torque/projects/whisper-tiny-benchmark/runner.py files
torque run ~/torque/projects/whisper-tiny-benchmark/runner.py replay --threads 4
torque run ~/torque/projects/whisper-tiny-benchmark/runner.py mic --threads 4
torque run ~/torque/projects/whisper-tiny-benchmark/runner.py mic --threads 4 --mic-trials 1 --guide-matrix --prompt-index 0
```

`files` compares two/four threads with three warm repetitions per clip. `replay`
paces the fixed clips through endpointing and adds trailing silence. `mic` asks
for three phrases after `MICROPHONE_READY`, with one finite utterance per trial.
Ctrl-C stops the experiment. Wait for each readiness message before speaking.
`--guide-matrix` uses a physical 3-2-1 countdown, hollow speak circle, working
dots and completion check. It allows a 30-second listening window, inside a
40-second finite capture. This optional mode temporarily owns the matrix and
releases it to normal status afterward. `--prompt-index` chooses one of the
three phrases for a single-trial run; the check marks completion, not accuracy.
Microphone samples remain in memory. Recognized microphone text is shown in the
terminal and excluded from saved metrics; the saved scores refer to prompt IDs.

Results are private local files under `results/`. RTF below one means processing
faster than the audio's duration. Warm decode time excludes model load. VAD
estimated end-to-final includes the silence wait; it is not an independently
annotated human speech-end measurement. File-end-to-final is a separate proxy.
Repeated six-clip results are a smoke test, not a general ASR accuracy claim.
Fixed-file and replay baselines have `.keep` markers so live retries cannot
prune them. The three-run/20 MiB limit removes only completed, unpinned runs;
if pinned runs fill that budget, export them before starting another run.

To reproduce setup without changing system packages, create `.venv` with
`python3 -m venv --without-pip .venv`, then use the existing installed runtime's
pip with `--python .venv/bin/python --isolated install --only-binary=:all:
--require-hashes --no-cache-dir -r requirements.lock`. The lock is for Linux ARM64
CPython 3.13. `prepare_model.py` downloads and verifies the pinned public weights.
`prepare_assets.py` is an off-board Mac/FFmpeg helper: it streams only enough of
the corpus archive to select the fixture pack. Preserve the frozen IDs/hashes
when comparing runs; changing inputs creates a different benchmark.

Run `selftest.py` with the private environment to check DSP/endpointing without
opening capture. The root repository suite covers scoring and process cleanup.
Artifacts and dependencies are ignored by Git; the harness and manifests are
reference source for reproducing the experiment.
