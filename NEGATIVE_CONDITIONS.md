# Negative conditions

All 16 rejected requests are retained, with the actual independent R outcome.
A process exit of zero does not certify finite model outputs. rxode2 safeZero,
safeLog and safePow were enabled for this source cohort and are recorded per run.

| Source model | Condition | QSPQuest diagnostic | R result |
| --- | --- | --- | --- |
| Cirincione_2017_exenatide | no_dose | domain | contains nonfinite/missing outputs |
| Xie_2019_agomelatine | no_dose | domain | finite guarded outputs |
| Xie_2019_agomelatine | retained_nlmixr-v032-agomelatine-baseline-pilot-v1 | domain | finite guarded outputs |
| indirect_1cpt_inhi_kin_r0rmaxcrmax | infusion | domain | finite guarded outputs |
| indirect_1cpt_inhi_kin_r0rmaxcrmax | no_dose | domain | finite guarded outputs |
| indirect_1cpt_inhi_kin_r0rmaxcrmax | retained_nlmixr-v032-numeric-pilot-v5 | domain | finite guarded outputs |
| indirect_1cpt_inhi_kout_r0rmaxcrmax | infusion | domain | finite guarded outputs |
| indirect_1cpt_inhi_kout_r0rmaxcrmax | no_dose | domain | finite guarded outputs |
| indirect_1cpt_inhi_kout_r0rmaxcrmax | retained_nlmixr-v032-numeric-pilot-v5 | domain | finite guarded outputs |
| indirect_prec_1cpt_inhi_r0rmaxcrmax | infusion | domain | finite guarded outputs |
| indirect_prec_1cpt_inhi_r0rmaxcrmax | no_dose | domain | finite guarded outputs |
| indirect_prec_1cpt_inhi_r0rmaxcrmax | retained_nlmixr-v032-required-inputs-pilot-v1 | domain | finite guarded outputs |
| indirect_prec_1cpt_stim_r0rmaxcrmax | double_dose | solver | solver failure |
| indirect_prec_1cpt_stim_r0rmaxcrmax | repeated_dose | solver | solver failure |
| tgi_no_sat_powerLaw | retained_nlmixr-v032-numeric-pilot-v5 | solver | finite guarded outputs |
| tgi_sat_genVonBertalanffy | retained_nlmixr-v032-numeric-pilot-v5 | solver | contains nonfinite/missing outputs |

Finite-time blow-up may produce enormous finite guarded output in R; consult
the source-domain analysis in `UPSTREAM_ISSUES.md`. Domain rejections are not
numerical mismatches or passing simulations. Parameters and events are preserved.

The separately corrected observation/history/window contracts and synthetic positive-potency variants remain private supplemental evidence. They are not added to the unchanged-source match count.
