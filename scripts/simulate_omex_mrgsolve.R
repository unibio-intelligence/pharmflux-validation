# Independent LSODA integration of equations generated from the archived SBML AST.
library(mrgsolve)
args<-commandArgs(trailingOnly=TRUE)
batch<-jsonlite::fromJSON(args[[1]],simplifyVector=FALSE)
reports<-list()
for(case in batch$cases){
 d<-jsonlite::fromJSON(case$experiment,simplifyVector=FALSE);folder<-case$folder
 report<-tryCatch({
  mod<-mrgsolve::mread('model',folder,soloc=file.path(folder,'compiled'),quiet=TRUE)
  states<-unlist(d$initial);parameters<-unlist(d$parameters);times<-unlist(d$times)
  apply_events<-function(time){for(e in d$events){if(e$time!=time)next
   env<-list2env(as.list(c(states,parameters,t=time)),parent=baseenv());env$clockorigin<-0
   for(def in d$definitions)eval(parse(text=def),env)
   updates<-lapply(e$updates,function(expr)eval(parse(text=expr),env))
   for(n in names(updates)){if(n %in% names(states))states[[n]]<<-updates[[n]] else parameters[[n]]<<-updates[[n]]}
  }}
  bounds<-sort(unique(c(times[[1]],tail(times,1),vapply(d$events,function(e)e$time,0.0))))
  apply_events(bounds[[1]]);frames<-list()
  atol<-min(unlist(d$solver$atol),1e-12);rtol<-min(d$solver$rtol,1e-9)
  for(i in seq_len(length(bounds)-1)){
   left<-bounds[[i]];right<-bounds[[i+1]];selected<-times[times>=left & times<=right];sample<-sort(unique(c(left,selected,right)))
   parameters[['clockorigin']]<-left
   mod<-mrgsolve::param(mod,as.list(parameters));mod<-mrgsolve::init(mod,as.list(states))
   solved<-mrgsolve::mrgsim_df(mod,tgrid=sample-left,rtol=rtol,atol=atol,maxsteps=1000000,obsonly=TRUE)
   if(nrow(solved)!=length(sample))stop('mrgsolve observation grid mismatch')
   solved$time<-sample;take<-sample %in% selected;if(i>1)take<-take & sample>left
   frame<-solved[take,c('time',unlist(d$output_columns)),drop=FALSE];names(frame)<-c('time',names(d$output_columns));frames[[i]]<-frame
   states<-unlist(solved[nrow(solved),names(states),drop=FALSE]);apply_events(right)
  }
  result<-do.call(rbind,frames);if(nrow(result)!=length(times)||any(!is.finite(as.matrix(result))))stop('incomplete trajectory')
  write.table(result,file.path(folder,'trajectory.csv'),sep=',',row.names=FALSE,quote=FALSE)
  list(status='executed',engine='mrgsolve',version=as.character(packageVersion('mrgsolve')),algorithm='LSODA',rtol=rtol,atol=atol,archive_sha256=d$archive_sha256,sbml_sha256=d$sbml_sha256,sedml_sha256=d$sedml_sha256,sampling=d$sampling,trajectory_sha256=digest::digest(file=file.path(folder,'trajectory.csv'),algo='sha256'))
 },error=function(e)list(status='failed',error=conditionMessage(e)))
 report$model_id<-d$model_id;report$scenario_id<-d$scenario_id
 jsonlite::write_json(report,file.path(folder,'provenance.json'),pretty=TRUE,auto_unbox=TRUE,digits=NA);reports[[length(reports)+1]]<-report
 jsonlite::write_json(reports,file.path(dirname(args[[1]]),'summary.json'),pretty=TRUE,auto_unbox=TRUE,digits=NA)
 cat(d$model_id,d$scenario_id,report$status,report$error,'\n')
}
