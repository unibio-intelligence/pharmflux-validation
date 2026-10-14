#!/usr/bin/env Rscript
# Independent synthetic reproducer: podo() reported amount versus its ODE value.
library(rxode2)
setRxThreads(1L)
model <- rxode2({
  d/dt(depot)=0
  d/dt(integrated_history)=podo(depot)
  reported_history=podo(depot)
})
events <- data.frame(ID=1,TIME=c(0,0,1,3,4),EVID=c(1,0,0,0,0),
                     AMT=c(10,0,0,0,0),CMT="depot",DUR=c(3,0,0,0,0))
actual <- as.data.frame(rxSolve(model,events=events,rtol=1e-11,atol=1e-14))
actual$expected_integral_of_reported_amount <- actual$time*10
print(actual)
cat("rxode2",as.character(packageVersion("rxode2")),"\n")
if (any(abs(actual$integrated_history-actual$expected_integral_of_reported_amount)>1e-7)) {
  cat("Inconsistent intrinsic: its reported value is 10, but the ODE integrates 10/3.\n")
} else cat("Intrinsic is consistent in this version.\n")
