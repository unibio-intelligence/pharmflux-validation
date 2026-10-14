# QSPQuest validation

Numerical comparisons for [QSPQuest](https://github.com/unibio-intelligence/qspquest):
what was tested, what matched, and where the results apply. These results describe
the engine build identified in [environment.json](environment.json); they do not
qualify later releases. A match means agreement within stated tolerances.

| Test | Coverage | Result |
| --- | --- | --- |
| OMEX simulations | 8 models, 47 scenarios, BDF and Rodas5P; six reference engines | All 47 scenarios matched for each reference and native solver |
| Additional source presets | 597 fixed presets | All matched their retained reference trajectories |
| Upstream conditions | 59 model definitions, 420 conditions per solver | 402 unchanged-reference matches, one explicit-history match, one discrepancy and 16 rejections |
| Corrected-reference conditions | Same conditions with a documented rxode2 infusion-history correction | All 404 valid conditions matched per solver; 16 remained rejected |
| Individual fitting | 1,906 contracts from 21 datasets, run with both native solvers | All 3,812 fits converged and matched parameters, likelihoods and predictions |

These cohorts overlap; their counts are not additive. Agreement supports the
tested equations, inputs and domains. It does not establish biological validity,
clinical suitability, all-model fitting support or population-fitting equivalence.

## Start here

- **Inspect or replay one result:** [First replay](docs/first-replay.md) verifies
  the archive and runs one retained preset with the CLI.
- **Understand the tests:** [Methods](METHODS.md) gives sampling rules,
  tolerances, parameter roles and optional independent-reference reruns.
- **Inspect the evidence:** [Summary](results/summary.json),
  [simulation rows](results/simulations.csv) and [fitting rows](results/fitting.csv).
  Compressed reports in `results/` retain detailed metrics and engine identities.

## What the comparisons establish

Simulation comparisons use identical observation grids and compare every declared
state and output. The OMEX references are rxode2, mrgsolve, OrdinaryDiffEq,
RoadRunner, COPASI and AMICI. The additional source presets use retained
source-specific references; replaying them does not regenerate those references.

Individual fits use bounded Gaussian likelihoods with fixed nuisance parameters
and no estimated random effects. Every native fit must converge and satisfy
parameter and prediction limits of `1e-6 + 0.001*abs(reference)` and a normalized
negative-log-likelihood difference of at most `1e-4`.
[Five datasets remain outside the fitting claim](REMAINING_FITTING_CONTRACTS.md).
Population fitting is outside this comparison set.

The 16 rejected conditions per solver cover undefined expressions, absent dose
history and trajectories without a valid finite solution. They are negative
outcomes, not simulation successes. See the
[condition-by-condition diagnostics](NEGATIVE_CONDITIONS.md).

An infusion-history discrepancy in rxode2 prompted a separate corrected-reference
comparison. Unmodified rxode2 failed seven of nine analytic history regressions;
the patch passed all nine. These regressions test the reference correction;
native agreement is assessed separately. The
[findings](UPSTREAM_ISSUES.md) preserve the original outcomes and the
[patch notes](upstream-patches/rxode2/README.md) describe reproduction.

## Scope and provenance

[Environment records](environment.json) identify the executed QSPQuest build and
the reference versions. Native results are freshly executed for that build;
retained reference trajectories are identified separately. Replaying one case
does not extend these comparisons to another engine build.

The COMBINE/OMEX archives are test fixtures. Native fitting and JSON model profiles
are identified explicitly. To find and use models, visit the companion
[model library](https://github.com/unibio-intelligence/qspquest-models).

Validation contributions are GPL-3.0-only; component notices remain applicable.
See [third-party notices](THIRD_PARTY_NOTICES.md).
