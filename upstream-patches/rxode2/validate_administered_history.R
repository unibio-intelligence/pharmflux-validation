#!/usr/bin/env Rscript
# UniBio Intelligence regression: administered amount is independent of infusion rate.
args <- commandArgs(TRUE)
if(length(args)!=1L) stop('usage: validate_rxode2_administered_history.R OUTPUT_DIRECTORY')
dir.create(args[1],recursive=TRUE,showWarnings=FALSE)
library(rxode2)
setRxThreads(1L)
model <- rxode2({
  f(depot)=availability
  d/dt(depot)=0
  d/dt(central)=0
  d/dt(integrated_depot_history)=podo0(depot)
  d/dt(integrated_central_history)=podo0(central)
  reported_depot=podo0(depot)
  reported_central=podo0(central)
})
scenarios <- list(
 bolus=data.frame(ID=1,TIME=0,EVID=1,AMT=10,CMT='depot',RATE=0,DUR=0),
 duration=data.frame(ID=1,TIME=0,EVID=1,AMT=10,CMT='depot',RATE=0,DUR=3),
 rate=data.frame(ID=1,TIME=0,EVID=1,AMT=10,CMT='depot',RATE=2,DUR=0),
 bioavailability=data.frame(ID=1,TIME=0,EVID=1,AMT=10,CMT='depot',RATE=0,DUR=3),
 unequal_repeat=data.frame(ID=1,TIME=c(0,5),EVID=1,AMT=c(10,20),CMT='depot',RATE=0,DUR=c(3,2)),
 overlap=data.frame(ID=1,TIME=c(0,1),EVID=1,AMT=c(10,21),CMT='depot',RATE=0,DUR=c(3,3)),
 compartments=data.frame(ID=1,TIME=c(0,1),EVID=1,AMT=c(10,21),CMT=c('depot','central'),RATE=0,DUR=c(3,3)),
 subjects=data.frame(ID=c(1,2),TIME=0,EVID=1,AMT=c(10,20),CMT='depot',RATE=0,DUR=c(3,4)),
 no_dose=data.frame(ID=integer(),TIME=numeric(),EVID=integer(),AMT=numeric(),CMT=character(),RATE=numeric(),DUR=numeric())
)
reports <- list()
for(name in names(scenarios)) {
 doses <- scenarios[[name]];ids <- if(nrow(doses))unique(doses$ID) else 1L
 times <- seq(0,8,by=.25)
 obs <- do.call(rbind,lapply(ids,function(id)data.frame(ID=id,TIME=times,EVID=0,AMT=0,CMT='depot',RATE=0,DUR=0)))
 events <- rbind(doses,obs);events <- events[order(events$ID,events$TIME,-events$EVID),]
 z <- as.data.frame(rxSolve(model,events=events,params=c(availability=if(name=='bioavailability').35 else 1),method='liblsoda',
     rtol=1e-11,atol=1e-13,maxsteps=1000000L,omega=NA,sigma=NA,returnType='data.frame'))
 if(!'id' %in% names(z))z$id <- ids[[1L]]
 worst <- 0
 for(id in ids)for(cmt in c('depot','central')) {
  sub <- z[z$id==id,];ds <- doses[doses$ID==id & doses$CMT==cmt,];ds <- ds[order(ds$TIME),]
  amount <- rep(0,nrow(sub));integral <- rep(0,nrow(sub));previous <- 0
  if(nrow(ds))for(i in seq_len(nrow(ds))) {
   integral <- integral+(ds$AMT[i]-previous)*pmax(sub$time-ds$TIME[i],0)
   amount[sub$time>=ds$TIME[i]] <- ds$AMT[i]
   previous <- ds$AMT[i]
  }
  delta <- max(abs(sub[[paste0('reported_',cmt)]]-amount),abs(sub[[paste0('integrated_',cmt,'_history')]]-integral))
  worst <- max(worst,delta)
 }
 path <- file.path(args[1],paste0(name,'.csv'));write.table(z,path,sep=',',quote=FALSE,row.names=FALSE)
 reports[[name]] <- list(status=if(is.finite(worst)&&worst<=1e-7)'match' else 'mismatch',max_absolute_error=worst,trajectory_sha256=digest::digest(file=path,algo='sha256'))
 cat(name,reports[[name]]$status,worst,'\n')
}
jsonlite::write_json(list(schema='qspquest.validation.rxode2-history/v1',rxode2_version=as.character(packageVersion('rxode2')),rxode2_library=dirname(find.package('rxode2')),limit=1e-7,cases=reports),file.path(args[1],'summary.json'),auto_unbox=TRUE,pretty=TRUE,digits=NA)
if(any(vapply(reports,function(x)x$status!='match',logical(1))))quit(status=1)
