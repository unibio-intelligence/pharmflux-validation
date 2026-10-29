# Test methods

The validation report is organized around simulation accuracy, parameter
estimation accuracy, and failure handling and domain limits. This document
explains the tested problems and acceptance criteria. Reference tools and
execution details support those assessments.

## Simulation accuracy

### States, outputs and solver coverage

For the eight OMEX models, reference adapters read SBML mathematical ASTs and
SED-ML sampling directly. All declared states and outputs must satisfy
`abs(native - reference) <= 1e-8 + 1e-4*abs(reference)` at matching observation
times. There is no trajectory interpolation. Scheduled simultaneous assignments
are segmented to preserve initial post-event and later pre-event samples.
`omex-simulations.omex` contains the eight original model archives and all 94
exact native requests, including solver-specific absolute tolerance declarations.

Native simulations use BDF and Rodas5P with their archived relative tolerances
and callback budgets. Rodas5P uses explicit state absolute tolerance 1e-14.
Independent adapter policies are visible in the scripts and per-case reports.
SBML time-symbol normalization changes notation only. AMICI uses its declared
Adams/fixed-point route for the Yuan cases whose fractional power has a singular
analytic Jacobian at zero; other ordinary cases use BDF/Newton.

The 597 additional fixed presets use the same numerical comparison limit and
exact time grids. `source-presets.omex` retains the exact native JSON models and
requests and a single independent reference CSV per preset. This suite replays
QSPQuest against those pinned scientific-source oracles; it does not regenerate
the original source validators. Their oracle/model/request hashes are retained
in `results/source-presets.json.gz`. Source-specific scope and attribution are
in `inputs/model-sources.json`; omitted or held source presets are outside the
597 denominator. This is deterministic evidence, not fitting or full-paper
reproduction.

### Upstream model and condition coverage

The 59 R definitions are pinned from nlmixr2lib 0.3.2. Every declared request is
retained: 420 conditions per native solver, with typical individual effects
(eta=0), fixed parameters, and explicit dose events. Source-to-native symbol
mappings are included. Comparisons require finite values and the exact time grid,
using `abs(delta) <= 1e-7 + 1e-6*abs(reference)` for every compared output.
The native output includes the mapped source states. The original-reference
lane enables rxode2's safeZero/safeLog/safePow policies; guarded finite outputs
are not treated as a solution of an undefined unguarded expression.

Counts distinguish 402 unchanged-reference matches, one additional
explicit-administered-amount reference match, one original infusion-history
discrepancy, and 16 rejections per native solver. Changing the reference is not
counted as an unchanged-reference pass.

The corrected-reference comparison used the pinned rxode2 source with an
explicit infusion-history patch. Each matrix had 404 valid matches and 16
rejections. Both R and native executions were fresh for the current recorded
engine. The correction changes reference infusion-history handling, without
altering native equations or request parameters. Original and corrected results
remain separate.

### Dosing and event behavior

Scheduled assignments and dose events are assessed at their declared sample
positions, including initial post-event and later pre-event observations. The
upstream infusion-history discrepancy is documented in `UPSTREAM_ISSUES.md`.

Nine analytic regressions assessed reference administered-dose history across
bolus, duration/rate infusions, bioavailability, unequal repeat and overlapping
doses, compartments, subjects, and a no-dose zero-history policy. The acceptance
limit was absolute error <= `1e-7`. Unmodified rxode2 failed seven of nine cases;
the patched reference passed all nine, with maximum absolute error below
`2e-13`. These are checks of the reference correction. They complement the
separate native-versus-reference simulation comparisons and do not independently
qualify QSPQuest dosing behavior.

## Parameter estimation accuracy

`individual-fitting.omex` retains every final qsp definition, observation row,
dose event, parameter role, physical bound, known error SD, reference equation,
and native fitting request. It is a native fitting profile in a COMBINE
container; no generic SED-ML estimation task is claimed. Observation/data source
hashes and the original GPL contributor records are included.

There are 1,906 contracts from 21 datasets, each executed with BDF and Rodas5P.
The objectives are fully normalized individual Gaussian likelihoods with no
estimated random effects. Known additive SD is 20% of maximum subject response.
The twelve ACOP examples estimate clearance or Vmax; theophylline estimates
clearance, volume and absorption rate; phenobarbital estimates clearance and
volume. Other contracts estimate the declared single response, weight, PK,
myelosuppression, PBPK, or binding parameter. Warfarin is PK-only. Neonatal
weights are simulated. These narrow contracts do not reproduce source population
analyses or qualify source-model fitting for all 59 nlmixr2lib entries.

A match requires all three:

- Every parameter difference <= `1e-6 + 0.001*abs(reference)`.
- Absolute normalized Gaussian negative-log-likelihood difference <= `1e-4`.
- Every fitted prediction difference <= `1e-6 + 0.001*abs(reference)`.

The native fit must also report convergence. The R route invokes actual
nlmixr2est estimation via FOCEI; scalar cases without random effects dispatch
to scalar optimization. Method-specific OFV values are not equated to normalized
NLL. WBC, PBPK and binding references use a positive log-multiplier within the
same physical bounds. Archived final WBC requests use the independently chosen
best converged fit from source start, seven log-spaced starts, and a physical
midpoint; no reference estimate supplies the native start. Replaying the final requests tests the recorded fitting contract.

Data exclusions remain explicit in each contract: the initial cohort excludes
time-zero observations and linear ACOP rows at/after the time-216 reset;
phenobarbital and WBC exclude too-sparse subjects. WBC legacy infusion start/stop
rows are paired into amount/rate events. The neonatal contracts retain time zero.

All 3,812 native fits converged and matched the three criteria above.
Five datasets and their concrete limits are listed in
`REMAINING_FITTING_CONTRACTS.md`. Population fitting equivalence is outside this report.

## Failure handling and domain limits

The original requests and parameters were retained when assessing undefined
expressions, missing dose history, poles and finite-time blow-up. Each native
solver rejected the same 16 conditions in the original and corrected reference
matrices. `NEGATIVE_CONDITIONS.md` lists the native domain/solver diagnostics and
actual R outcomes; `UPSTREAM_ISSUES.md` provides the algebra and history analysis.

Reference outcomes are evaluated for mathematical validity, rather than process
exit status alone. The original reference enables safeZero, safeLog and safePow;
finite values from these guards do not establish a solution of an undefined
unguarded expression. Nonfinite/missing outputs and solver failures are recorded
explicitly. Rejected requests remain outside the successful-simulation count.
These checks cover the recorded negative conditions; they do not cover all
possible invalid inputs.

## Reference methods and environments

`environment.json` records the exported QSPQuest compiler source hash, executable
hash, DiffSol backend hash, and reference versions. Replays record the
binary hash actually used; a different platform binary will differ even when
built from the same source. The reported evidence applies to the recorded engine build.

Python needs NumPy, pandas, and python-libsbml. R references use rxode2 5.1.8,
nlmixr2lib 0.3.2, nlmixr2est 7.1.0, jsonlite, digest, and nlme. Configure
`R_LIBS_USER` if these are in a separate library. Additional engines need their
recorded environments: mrgsolve in R, OrdinaryDiffEq in Julia, or the appropriate
RoadRunner/COPASI/AMICI Python package. See `environment.json` for exact recorded
versions. Solvers in different engines need not be identical: rxode2 uses LSODA,
mrgsolve/COPASI use LSODA, RoadRunner uses CVODE BDF, and OrdinaryDiffEq uses
Rodas5P. BDF and LSODA are different algorithms.

## Supporting evidence

`results/summary.json` gives aggregate counts; CSV files give one row per
comparison; `.json.gz` files preserve full per-case metrics and identities.
Read a detailed report with Python's `gzip.open` and `json.load`. `manifest.json`
checksums this minimal snapshot. `scripts/verify.py` checks all checksums,
COMBINE manifests, fixture-member hashes, result counts, and engine identities.
The inputs are test fixtures, not another public model catalog. Replays create
raw predictions, trajectories and logs only in the requested new directory.

## Optional rerun instructions

For a complete dependency-free setup and one selected comparison, start with
[First replay](docs/first-replay.md). The commands below run optional reference
engines or additional recorded tests.
The validation findings and scope are reported above and in `README.md`.
Install the dependencies listed under reference methods and environments, then
set `QSPQUEST_EXECUTABLE` to the QSPQuest CLI.

```sh
python scripts/verify.py
export QSPQUEST_EXECUTABLE=/path/to/qspquest
python scripts/reproduce.py --suite omex-rxode2 \
  --cli "$QSPQUEST_EXECUTABLE" --output replay-omex
```

For independent engines, use `--suite mrgsolve`, `ordinarydiffeq`, `roadrunner`,
`copasi` or `amici`. A selected model can be run with:

```sh
python scripts/reproduce.py --suite mrgsolve \
  --model qspquest_diffdose_2026_idr_benchmark \
  --cli "$QSPQUEST_EXECUTABLE" --output replay-mrgsolve
```

The runner freshly executes both native solvers before generating and comparing
the reference. Omit `--model` for all eight models. Additional source presets
use `--suite presets`; this compares new native trajectories against the retained
source references without regenerating the original source validators.

For upstream conditions, use `--suite nlmixr2-bdf` or `nlmixr2-rodas5p`:

```sh
python scripts/reproduce.py --suite nlmixr2-bdf \
  --model PK_1cmt --case baseline \
  --cli "$QSPQUEST_EXECUTABLE" --output replay-nlmixr2
```

Omit `--model` and `--case` for the complete matrix. For the corrected-reference
comparison, follow `upstream-patches/rxode2/README.md`, put the patched library
first in `R_LIBS_USER`, and use `nlmixr2-patched-bdf` or
`nlmixr2-patched-rodas5p`. The runner checks the analytic dose-history regressions
before the matrix comparison.

For fitting, `--model` selects the dataset and `--case` selects the subject:

```sh
python scripts/reproduce.py --suite fitting \
  --model Bolus_1CPT --case 1 \
  --cli "$QSPQUEST_EXECUTABLE" --output replay-fit
```

Omit both selectors for all 3,812 fits. Reruns write new trajectories, optimizer
output and logs to the chosen output directory.

## Engine and reference identities

`environment.json` identifies the QSPQuest build used for the native executions.
Each comparison records the input hashes and actual native execution identity.
Independent reference trajectories retain their original bytes and reference
engine versions; their reuse is recorded explicitly. A comparison against a
retained reference is not a new execution of that reference engine.
