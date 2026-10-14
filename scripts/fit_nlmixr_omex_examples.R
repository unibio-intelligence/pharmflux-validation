#!/usr/bin/env Rscript
args <- commandArgs(trailingOnly=TRUE)
plan <- jsonlite::fromJSON(file.path(args[[1L]],'plan.json'),simplifyVector=FALSE)
rxode2::setRxThreads(1L)
results <- list()
ui_cache <- new.env()
for (case in plan$cases) {
 result <- tryCatch({
  folder <- if (grepl('^/',case$directory)) case$directory else file.path(args[[1L]],case$directory)
  definitions <- vapply(names(case$parameters),function(n) {
   if (n %in% unlist(case$estimated)) {
    b <- unlist(case$bounds[[n]])
    sprintf('%s <- c(%.17g,%.17g,%.17g)',n,b[[1]],case$parameters[[n]],b[[2]])
   } else sprintf('%s <- fixed(%.17g)',n,case$parameters[[n]])
  },'')
  rhs <- '0'
  if (case$oral) rhs <- paste(rhs,'+ ka*depot')
  rhs <- paste(rhs,if(case$mm) '- vmax*(central/vc)/(km+central/vc)' else '- cl/vc*central')
  if (case$two) rhs <- paste(rhs,'- q*central/vc + q*peripheral/vp')
  equations <- c(paste0('d/dt(central) <- ',rhs))
  if (case$oral) equations <- c(equations,'d/dt(depot) <- -ka*depot')
  if (case$two) equations <- c(equations,'d/dt(peripheral) <- q*central/vc-q*peripheral/vp')
  text <- paste0('function(){ini({',paste(definitions,collapse=';'),';add_sd <- fixed(',case$sigma,')});model({',paste(equations,collapse=';'),';cp <- central/vc;cp ~ add(add_sd)})}')
  data <- read.csv(file.path(folder,'data.csv'))
  if (case$synthetic) {
    # Shared compiled equation code; source nuisance values remain covariates.
    key <- paste(case$two,case$mm,case$oral,sep='_')
    target <- unlist(case$estimated)[[1L]]
    cov_def <- vapply(names(case$parameters),function(n)
      paste0(n,' <- ',if(n==target)'scale * ' else '',toupper(paste0('SRC_',n))), '')
    text <- paste0('function(){ini({scale <- c(.05,.8,20);add_sd <- fixed(1)});model({',
      paste(cov_def,collapse=';'),';',paste(equations,collapse=';'),';cp <- central/vc/SRC_SIGMA;cp ~ add(add_sd)})}')
    if (!exists(key,ui_cache,inherits=FALSE)) assign(key,nlmixr2est::nlmixr2(eval(parse(text=text))),ui_cache)
    ui <- get(key,ui_cache)
    for(n in names(case$parameters)) data[[toupper(paste0('SRC_',n))]] <-
      case$parameters[[n]] / if(n==target) .8 else 1
    data$SRC_SIGMA <- case$sigma
    data$DV <- data$DV/case$sigma
  } else ui <- nlmixr2est::nlmixr2(eval(parse(text=text)))
  fit <- nlmixr2est::nlmixr2(ui,data=data,est='focei',control=nlmixr2est::foceiControl(print=0L,maxOuterIterations=1000L,sigdig=7L,
    rxControl=rxode2::rxControl(method='liblsoda',atol=1e-10,rtol=1e-9)))
  frame <- as.data.frame(fit)
  if(case$synthetic) {frame$DV <- frame$DV*case$sigma;frame$IPRED <- frame$IPRED*case$sigma}
  # Known noise and no ETAs: fully normalized observation likelihood.
  nll <- sum(log(case$sigma*sqrt(2*pi))+.5*((frame$DV-frame$IPRED)/case$sigma)^2)
  estimates <- if(case$synthetic) setNames(list(unname(nlme::fixef(fit)[['scale']]) * case$parameters[[target]]/.8),target) else as.list(nlme::fixef(fit)[unlist(case$estimated)])
  list(status='executed',dataset=case$dataset,subject=case$subject,parameters=estimates,
       convergence=fit$convergence,nll=nll,predictions=frame[,c('TIME','DV','IPRED')],
       nlmixr2est=as.character(packageVersion('nlmixr2est')),rxode2=as.character(packageVersion('rxode2')),
       solver='liblsoda',source_model_text=text)
 },error=function(e)list(status='failed',dataset=case$dataset,subject=case$subject,error=conditionMessage(e)))
 jsonlite::write_json(result,file.path(folder,'nlmixr2-result.json'),pretty=TRUE,auto_unbox=TRUE,digits=NA,null='null')
 results[[length(results)+1L]] <- result
 cat(case$dataset,case$subject,result$status,'\n');flush.console()
}
jsonlite::write_json(results,file.path(args[[1L]],'nlmixr2-executions.json'),pretty=TRUE,auto_unbox=TRUE,digits=NA,null='null')
