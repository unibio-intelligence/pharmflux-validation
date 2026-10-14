# Example-data fitting contract coverage

Twenty-one of the 26 pinned nlmixr2data datasets now have matched individual Gaussian contracts: 1,906 contracts and 3,812 converged native fits, using both BDF and Rodas5P against actual nlmixr2est estimation. [Methods](METHODS.md) records equations, estimands, fixed nuisance parameters, observations, bounds and numerical limits.

The six additional completed datasets are Wang2007 (10 nonlinear response contracts), neonatal_wt (189 simulated weight contracts), warfarin (32 PK-only contracts), wbcSim (44 myelosuppression contracts), mavoglurant (120 PBPK contracts), and nimoData (12 nonlinear binding contracts). Their narrow individual fits do not reproduce the source population analyses. Neonatal weights here are simulated, not the unavailable real patient dataset.

| Dataset outside the fitting claim | Reason and required work |
| --- | --- |
| pump | Failure counts and operating durations require a count/event-rate likelihood. The native Gaussian concentration likelihood is unsuitable; a discrete-likelihood fitting capability is needed. |
| rats | The source problem uses correlated binomial/probit responses. A matched binomial/probit and correlation contract is required; Gaussian fitting would change the problem. |
| metabolite | The dataset supplies parent/metabolite observations but the located package/example documentation does not establish a complete dose, initial-state, conversion-scale and multi-output estimation specification. Obtain that source contract before fitting. |
| invgaussian | The legacy source equation and parameter specification were located. Its inverse-Gaussian absorption input has a conditional zero-time extension; the attempted native contract is rejected by the current time-dependent conditional qualification guard. This is a native capability/contract limitation, not missing data or proof that the source mathematics is invalid. It needs a qualified conditional input implementation before a matched fitting claim. |
| nmtest | This is an event/simulation reference corpus, not ordinary observed clinical fitting data. It is usable for simulation semantics. A separately labelled synthetic recovery contract is possible but is outside the present fitting cohort. |

Source archive hashes and the used subject-level contracts are pinned in inputs/individual-fitting.omex; the full source-data export remains outside this minimal repository. Source documentation, numerical source coordinates and data availability do not establish redistributable patient data or source-specific fitting equivalence for all 59 nlmixr2lib entries. No unsuitable problem is counted as passing.
