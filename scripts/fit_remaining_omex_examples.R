# GPL validation adapter for the explicitly declared narrow source-example contracts.
args<-commandArgs(trailingOnly=TRUE);root<-args[[1]];plan<-jsonlite::fromJSON(file.path(args[[1]],'plan.json'),simplifyVector=FALSE);cache<-new.env();reports<-list();rxode2::setRxThreads(1)
for(case in plan$cases){
 if(Sys.getenv('FIT_ONLY_DATASET')!='' && case$dataset!=Sys.getenv('FIT_ONLY_DATASET'))next
 folder<-if(grepl('^/',case$directory)) case$directory else file.path(root,case$directory)
 result<-tryCatch({
  target<-unlist(case$estimated)[[1]];base<-case$parameters[[target]];b<-unlist(case$bounds[[target]])
  logsearch<-case$dataset %in% c('wbcSim','nimoData','mavoglurant')
  key<-case$dataset
  if(!exists(key,cache,inherits=FALSE)){
   assignments<-vapply(names(case$parameters),function(n)paste0(n,'=',if(n==target)if(logsearch)'exp(scale)*' else 'scale*' else '',toupper(paste0('SRC_',n))),'')
   model<-gsub('cp=','source_cp=',case$r_model,fixed=TRUE)
   text<-paste0('function(){ini({scale<-c(',if(logsearch)log(b[[1]]/base) else b[[1]]/base,',',if(logsearch)0 else 1,',',if(logsearch)log(b[[2]]/base) else b[[2]]/base,');add_sd<-fixed(1)});model({',paste(assignments,collapse=';'),';',model,';cp=source_cp/SRC_SIGMA;cp~add(add_sd)})}')
   assign(key,list(ui=nlmixr2est::nlmixr2(eval(parse(text=text))),text=text),cache)
  }
  cached<-get(key,cache);data<-read.csv(file.path(folder,'data.csv'))
  for(n in names(case$parameters))data[[toupper(paste0('SRC_',n))]]<-case$parameters[[n]]
  data$SRC_SIGMA<-case$sigma;data$DV<-data$DV/case$sigma
  fit<-nlmixr2est::nlmixr2(cached$ui,data,est='focei',control=nlmixr2est::foceiControl(print=0,maxOuterIterations=1000,sigdig=7,rxControl=rxode2::rxControl(method='liblsoda',rtol=1e-9,atol=1e-10)))
  frame<-as.data.frame(fit);frame$DV<-frame$DV*case$sigma;frame$IPRED<-frame$IPRED*case$sigma
  list(status='executed',dataset=case$dataset,subject=case$subject,parameters=setNames(list((if(logsearch)exp(unname(nlme::fixef(fit)[['scale']])) else unname(nlme::fixef(fit)[['scale']]))*base),target),convergence=fit$convergence,nll=sum(log(case$sigma*sqrt(2*pi))+.5*((frame$DV-frame$IPRED)/case$sigma)^2),predictions=frame[,c('TIME','DV','IPRED')],nlmixr2est=as.character(packageVersion('nlmixr2est')),rxode2=as.character(packageVersion('rxode2')),solver='liblsoda',source_model_text=cached$text,reference_coordinate=if(logsearch)'log multiplier; same physical parameter bounds and likelihood' else 'multiplier')
 },error=function(e)list(status='failed',dataset=case$dataset,subject=case$subject,error=conditionMessage(e)))
 jsonlite::write_json(result,file.path(folder,'nlmixr2-result.json'),pretty=TRUE,auto_unbox=TRUE,digits=NA,null='null');reports[[length(reports)+1]]<-result
 jsonlite::write_json(reports,file.path(args[[1]],'nlmixr2-executions.json'),pretty=TRUE,auto_unbox=TRUE,digits=NA,null='null');cat(case$dataset,case$subject,result$status,result$error,'\n');flush.console()
}
