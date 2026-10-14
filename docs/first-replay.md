# Verify the archive and replay one preset

This tutorial checks the validation files, runs one source preset with your
QSPQuest CLI, and compares its full trajectory against the retained reference.
It requires Python 3.11 or newer and a built QSPQuest CLI. No additional Python
packages or reference-engine installation are needed for this preset replay.

Run these commands from the validation repository root. If you need to build the
CLI, follow the [engine installation guide](https://github.com/unibio-intelligence/qspquest/blob/main/docs/installation.md)
first. This snapshot records QSPQuest 0.1.0 with compiler source hash
`34354d12c5c962cca95fab09ceb5c1084100f2b87e41f89269868ad5942b97ec`.
The engine suite file pins this exact validation manifest. Build the engine
revision supplied with that suite to reproduce its source identity; version
`0.1.0` alone does not identify source bytes. A later engine may also replay the
fixture, but its result is a new comparison with its own identity.

## Set up and verify

Create the environment and output beside the checkout so archive verification
continues to cover only the release files:

```sh
python3 -m venv ../qspquest-validation-env
. ../qspquest-validation-env/bin/activate
python --version
python -B scripts/verify.py
python -B -m unittest discover -s scripts -p 'test_*.py'
export QSPQUEST_EXECUTABLE="$(cd ../qspquest && pwd)/target/release/qspquest"
test -x "$QSPQUEST_EXECUTABLE"
```

The executable assignment assumes a sibling checkout named `qspquest`. If yours
is elsewhere, set `QSPQUEST_EXECUTABLE` to its absolute executable path instead.
Verification reports 2,841 archived simulation comparisons and 3,812 fitting
comparisons with consistent recorded QSPQuest identities. The unit tests
exercise comparison failures as well as successful matches; they do not rerun
those scientific matrices.

## Run one comparison

```sh
python -B scripts/reproduce.py --suite presets \
  --model qspquest-ortiz-2024-ravulizumab-nmosd-pkpd \
  --case week50-40-60-pk-free-c5-ode \
  --cli "$QSPQUEST_EXECUTABLE" --output ../qspquest-preset-replay
```

A successful run prints `{"matched": 1}`. Inspect its saved summary and the actual
binary identity:

```sh
python -m json.tool ../qspquest-preset-replay/replay-engine.json
python -m json.tool ../qspquest-preset-replay/summary.json
```

`summary.json` contains one case with three state/output comparison columns
across 353 observation times. `max_scaled_error <= 1` means the values satisfy
`abs(actual-reference) <= 1e-8 + 1e-4*abs(reference)` at the exact observation
times. Missing columns, nonfinite values and incomplete trajectories fail the
comparison. `replay-engine.json` identifies the executable you actually ran;
`same_binary: false` is expected for another build or platform. Compare
`compiler_source_sha256` separately: it should match `environment.json` for the
recorded source, even when executable bytes differ. A source-hash mismatch means
you built different engine sources, not that the archived values were recomputed
with your executable.

The preset uses its archived native model and request. It checks deterministic
simulation against retained source trajectories, not physical-unit qualification,
fitting, population inference or a complete source-paper reproduction.

## Common problems and next steps

- If the output directory already exists, choose a new `--output` path. Results
  are never silently overwritten.
- If the executable cannot be found, check `QSPQUEST_EXECUTABLE` with `test -x`
  and use an absolute path.
- A checksum failure means the snapshot has changed or is incomplete. Restore
  the release files before treating its archived evidence as intact.
- A numerical failure on another engine build is a new result to investigate;
  do not change tolerances to make it pass. Keep the output directory and logs.

[Methods](../METHODS.md#optional-rerun-instructions) documents the optional R,
Julia and other independent-reference workflows and their recorded dependencies.

Replay inputs use the declared `qspquest.*` formats. The runner verifies archive
and member hashes before execution and records identical source and executed
input hashes in its `*-inputs.json` receipts. Unsupported formats are rejected.
