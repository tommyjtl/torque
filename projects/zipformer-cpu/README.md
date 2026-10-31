# CPU Zipformer

Selected baseline for the next local English speech prototype on the UNO Q's
Linux processor. The recorded-clip benchmark had a median 0.387 s last-segment
finalization delay after file end, with 18/18 trials below one second and
4/136 word errors. Live microphone buffering and whole-turn detection are next
to validate. The 0.3-second endpoint can split longer speech into several
segments; use push-to-talk or explicit turn handling before executing commands.

This folder preserves the tested native executable, pinned English model and
six public test clips. The launcher always selects CPU execution and disables
diagnostic profiling; it exposes no GPU mode. The retained executable is the
hash-identical matched benchmark build, which contains optional GPU backend
code but is run in CPU mode. System graphics drivers remain installed for
other applications. No GPU experiment files or build toolchain are needed here.

After the board has been prepared:

```bash
torque run ~/torque/projects/zipformer-cpu/main.py --bulk --first-clip
torque run ~/torque/projects/zipformer-cpu/main.py
```

Both are finite recorded-file checks, with no microphone capture or recognized
command execution. `--bulk` checks correctness without real-time pacing and
must not be interpreted as speech-end latency. The default paced run uses all
six clips once; `--repeats 3` repeats them three times after an excluded warm-up.
Wait for completion before starting another run. Results are limited to a
10 MiB budget; export them before rerunning once it fills.

## Live voice experiment

The CPU streaming worker supports the Media Carrier microphone through Torque's
capture API and its native stateful 48 kHz-to-16 kHz resampler:

```bash
torque run ~/torque/projects/zipformer-cpu/live.py --selftest --decoder modified_beam_search
torque run ~/torque/projects/zipformer-cpu/live.py --free-speech --decoder modified_beam_search
```

The self-test does not record. The live command announces capture, counts 3–2–1
on the matrix, then displays a hollow circle. Say one short sentence and pause;
Ctrl-C stops. It is finite, retains ordered input and restores microphone
routing/status ownership. PCM and microphone transcript text are not saved;
recognized text is displayed in the calling terminal. No recognized command is
executed. `--decoder greedy_search` selects the original decoder.

Initial live trials were responsive but had connected-speech recognition errors
with both decoders. Recorded-clip performance is not live accuracy acceptance.
The fast endpoint is for short single phrases and can end during a longer pause.
Use explicit turn handling before integrating with the agent.

The worker executable is retained for use without build tools. `build_live.py`
records how it was linked against the archived development libraries; rebuilding
requires restoring that build context. It is not needed for normal execution.

Model: small English streaming Zipformer, publisher-declared Apache-2.0.
Fixtures: LibriSpeech test-clean, CC BY 4.0, Vassil Panayotov, Daniel Povey,
Guoguo Chen and Sanjeev Khudanpur. Model/fixture SHA-256 hashes and the native
build provenance are retained in the small manifests. GPU benchmark evidence
remains archived off-board and in the performance report.
