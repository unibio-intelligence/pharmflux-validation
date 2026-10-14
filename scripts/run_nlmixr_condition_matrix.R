#!/usr/bin/env Rscript
# Execute every declared deterministic condition from a pinned native model UI.
args <- commandArgs(trailingOnly=TRUE)
if (length(args)!=2L) stop("usage: run_nlmixr_condition_matrix.R MODEL_PLAN.json OUTPUT")
runner_path <- sub("^--file=", "", grep("^--file=",commandArgs(),value=TRUE)[[1L]])
history_helper <- file.path(dirname(normalizePath(runner_path)),"nlmixr_dose_history_reference.R")
source(history_helper)
plan <- jsonlite::fromJSON(args[[1L]],simplifyVector=FALSE)
if (!identical(as.character(utils::packageVersion("nlmixr2lib")),"0.3.2")) stop("wrong nlmixr2lib version")
if (!is.null(plan$source_file)) {
  source_path <- plan$source_file
  if (!grepl("^/",source_path)) source_path <- file.path(dirname(normalizePath(args[[1L]])),source_path)
  if (!identical(digest::digest(file=source_path,algo="sha256"),plan$source_sha256)) stop("native source pin differs")
  source_env <- new.env(parent=globalenv())
  sys.source(source_path,envir=source_env)
  ui <- rxode2::rxode2(get(plan$source_function,envir=source_env,inherits=FALSE))
} else {
  if (!identical(digest::digest(file=plan$model_ui,algo="sha256"),plan$model_ui_sha256)) stop("native UI pin differs")
  ui <- readRDS(plan$model_ui)
}
rxode2::setRxThreads(1L)
dir.create(args[[2L]],recursive=TRUE,showWarnings=FALSE)
reports <- list()
for (case in plan$cases) {
  folder <- file.path(args[[2L]],case$condition_id)
  dir.create(folder,recursive=TRUE,showWarnings=FALSE)
  report <- tryCatch({
    if (!identical(digest::digest(file=case$r_request,algo="sha256"),case$r_request_sha256)) stop("request pin differs")
    request <- jsonlite::fromJSON(case$r_request,simplifyDataFrame=TRUE)
    if (!identical(request$options$variability,"typical")) stop("require fixed typical individual")
    set.seed(as.integer(request$seed));rxode2::rxSetSeed(as.integer(request$seed))
    solver <- utils::modifyList(list(method="liblsoda",rtol=1e-11,atol=1e-14,maxsteps=1000000L),request$options$solver)
    object <- ui
    correction <- NULL
    if (!is.null(request$reference_correction)) {
      if (!identical(request$reference_correction,"explicit_administered_amount_for_podo")) stop("unknown reference correction")
      fixed <- prepare_administered_amount_history(ui,request$dataset)
      object <- fixed$object
      request$dataset <- fixed$events
      correction <- fixed$correction
      correction$helper_sha256 <- digest::digest(file=history_helper,algo="sha256")
    }
    call <- c(list(object=object,events=request$dataset,seed=as.integer(request$seed),
                   cores=1L,nSub=1L,nStud=1L,omega=NA,sigma=NA,
                   safeZero=TRUE,safeLog=TRUE,safePow=TRUE),solver)
    if (!is.null(request$comparison_fixed_parameters)) call$params <- unlist(request$comparison_fixed_parameters)
    frame <- as.data.frame(do.call(rxode2::rxSolve,call))
    utils::write.table(frame,file.path(folder,"trajectory.csv"),sep=",",row.names=FALSE,quote=FALSE)
    list(status="executed",rows=nrow(frame),solver=solver,reference_correction=correction,
         domain_policy=list(safeZero=TRUE,safeLog=TRUE,safePow=TRUE),
         trajectory_sha256=digest::digest(file=file.path(folder,"trajectory.csv"),algo="sha256"))
  },error=function(e) list(status="failed",error=conditionMessage(e)))
  report$condition_id <- case$condition_id
  report$model_id <- plan$model_id
  report$model_ui_sha256 <- plan$model_ui_sha256
  report$source_sha256 <- plan$source_sha256
  report$r_request_sha256 <- case$r_request_sha256
  report$R_version <- R.version.string
  report$rxode2_version <- as.character(utils::packageVersion("rxode2"))
  report$nlmixr2lib_version <- as.character(utils::packageVersion("nlmixr2lib"))
  jsonlite::write_json(report,file.path(folder,"provenance.json"),auto_unbox=TRUE,pretty=TRUE,digits=NA)
  reports[[length(reports)+1L]] <- report
  jsonlite::write_json(reports,file.path(args[[2L]],"summary.json"),auto_unbox=TRUE,pretty=TRUE,digits=NA)
  cat(plan$model_id,case$condition_id,report$status,"\n");flush.console()
}
