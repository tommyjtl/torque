# Moonshine Tiny Streaming experiment

Isolated, finite CPU screening on UNO Q, using the same six attributed English
clips as the Whisper experiment. It does not add speech recognition to Torque,
execute recognized commands, flash firmware or restart services.

The installed Torque Python runs `runner.py`; a private environment runs the
native recognizer. Select Tiny Streaming explicitly: the package's English
default is a larger model. Dependencies and assets are pinned in
`requirements.lock` and `model-lock.json`. `prepare_models.py` downloads that
architecture and verifies the saved model hashes. Fixtures are CC BY 4.0, with
attribution/provenance and hashes in `fixtures.json`.

```bash
torque run ~/torque/projects/moonshine-tiny-benchmark/runner.py files
torque run ~/torque/projects/moonshine-tiny-benchmark/runner.py files --interval 0.1 --vad-window 0.15
torque run ~/torque/projects/moonshine-tiny-benchmark/runner.py files --interval 0.1 --vad-window 0.15 --final-only
```

Use `--run TIMESTAMP` to keep configurations in the same result bundle. Three
seconds of paced silence follow each file, allowing natural final callbacks.
Calling `stop()` can force a final transcript; those callbacks are tagged and
excluded from natural-final latency claims. File-end timing is a proxy for
speech-end timing, since the corpus has no independent endpoint annotations.
Results remain bounded to 20 MiB; existing measurements are not auto-pruned.

The optional `mic` mode uses one finite, matrix-guided trial: 3-2-1 countdown,
hollow speak circle, working dots and completion check. It drains ordered PCM
through a bounded queue and fails rather than dropping samples if inference
falls behind. Microphone samples and transcript text are not saved in results.
The live mode requires a separate readiness check and has not been accepted
on the physical input path. A completion check indicates processing finished,
not recognition correctness or sub-one-second performance.

`report.py` summarizes saved measurements without loading a model or microphone.
Private environments, downloaded models, audio fixtures and raw result bundles
are excluded from Git.
