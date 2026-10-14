#!/usr/bin/env Rscript
# Deterministic OMEX simulations using the nlmixr2/rxode2 numerical engine.
# Scheduled SBML assignments use simultaneous right-hand sides. Segments retain
# absolute time and exact pre-event rows; the initial row follows initial events.

load_omex_rxode2 <- function(archive, scenario, python = Sys.getenv("OMEX_PYTHON", "python3"),
                            adapter = Sys.getenv("OMEX_ADAPTER", "scripts/omex_to_rxode2.py")) {
  path <- tempfile(fileext = ".json")
  on.exit(unlink(path))
  status <- system2(python, c(shQuote(adapter), shQuote(archive), "--scenario", shQuote(scenario), "--output", shQuote(path)))
  if (status != 0L) stop("OMEX adapter rejected archive")
  document <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  list(model = rxode2::rxode2(document$model_code), experiment = document)
}

simulate_omex_rxode2 <- function(loaded, output = NULL, rtol = NULL, atol = NULL) {
  d <- loaded$experiment
  if (!identical(d$schema, "ubi.omex.rxode2/v1")) stop("unsupported experiment schema")
  rxode2::setRxThreads(1L)
  states <- unlist(d$initial)
  parameters <- unlist(d$parameters)
  times <- unlist(d$times)
  if (any(!is.finite(c(states, parameters, times)))) stop("nonfinite input")
  events <- d$events
  boundaries <- sort(unique(c(times[[1L]], vapply(events, function(e) e$time, 0.0), tail(times,1L))))
  options <- d$solver
  if (!is.null(rtol)) options$rtol <- rtol
  if (!is.null(atol)) options$atol <- atol
  apply_events <- function(time) {
    matching <- Filter(function(e) identical(as.numeric(e$time), as.numeric(time)), events)
    for (e in matching) {
      env <- list2env(as.list(c(states,parameters,t=time)), parent=baseenv())
      env$clockorigin <- 0
      # Code here was generated exclusively from the closed SBML AST renderer.
      for (definition in d$definitions) eval(parse(text=definition), env)
      updates <- lapply(e$updates, function(expr) eval(parse(text=expr),env))
      for (name in names(updates)) {
        value <- updates[[name]]
        if (length(value)!=1L || !is.finite(value)) stop("invalid event assignment")
        if (name %in% names(states)) states[[name]] <<- value else parameters[[name]] <<- value
      }
    }
  }
  apply_events(boundaries[[1L]])
  frames <- list()
  for (i in seq_len(length(boundaries)-1L)) {
    left <- boundaries[[i]]; right <- boundaries[[i+1L]]
    selected <- times[times>=left & times<=right]
    sample <- sort(unique(c(left,selected,right)))
    parameters[["clockorigin"]] <- left
    solved <- as.data.frame(rxode2::rxSolve(loaded$model, params=parameters, inits=states,
                          events=data.frame(time=sample-left, evid=0L), method=options$method,
                          rtol=options$rtol, atol=unlist(options$atol), maxsteps=1000000L,
                          safeZero=FALSE, safeLog=FALSE, safePow=FALSE,
                          cores=1L, omega=NA, sigma=NA, returnType="data.frame"))
    solved$time <- solved$time + left
    if (nrow(solved)!=length(sample) || any(!is.finite(as.matrix(solved[,unlist(d$output_columns),drop=FALSE])))) stop("incomplete or nonfinite trajectory")
    if (any(abs(solved$time-sample)>1e-10)) stop("rxode2 observation grid mismatch")
    # Restore exact requested coordinates after subtraction/addition rounding.
    solved$time <- sample
    take <- solved$time %in% selected
    if (i>1L) take <- take & solved$time>left
    frame <- solved[take,c("time",unlist(d$output_columns)),drop=FALSE]
    names(frame) <- c("time",names(d$output_columns))
    frames[[i]] <- frame
    states <- unlist(solved[nrow(solved),names(states),drop=FALSE],use.names=TRUE)
    apply_events(right)
  }
  result <- do.call(rbind,frames)
  rownames(result) <- NULL
  if (nrow(result)!=length(times) || any(abs(result$time-times)>1e-10)) stop("stitched trajectory mismatch")
  if (!is.null(output)) utils::write.table(result,output,sep=",",row.names=FALSE,col.names=TRUE,quote=FALSE)
  list(trajectory=result, provenance=list(schema="ubi.omex.rxode2-result/v1",
       model_id=d$model_id, model_version=d$model_version, scenario_id=d$scenario_id,
       archive_sha256=d$archive_sha256, adapter_sha256=d$adapter_sha256,
       sbml_sha256=d$sbml_sha256, sedml_sha256=d$sedml_sha256,
       R_version=R.version.string,rxode2_version=as.character(utils::packageVersion("rxode2")),
       solver=options,archived_solver_policy=d$archived_solver_policy,
       domain_policy=list(safeZero=FALSE,safeLog=FALSE,safePow=FALSE),sampling=d$sampling,rows=nrow(result),
       scope="Deterministic time-course simulation; no population variability or parameter fitting"))
}

if (sys.nframe()==0L) {
  args <- commandArgs(trailingOnly=TRUE)
  if (length(args)!=2L) stop("usage: simulate_omex_rxode2.R EXPERIMENT.json OUTPUT_DIRECTORY")
  dir.create(args[[2L]],recursive=TRUE,showWarnings=FALSE)
  d <- jsonlite::fromJSON(args[[1L]],simplifyVector=FALSE)
  cache <- new.env(parent=emptyenv())
  cases <- if (identical(d$schema,"ubi.omex.rxode2-batch/v1")) d$cases else list(list(experiment=args[[1L]],output="."))
  reports <- list()
  for (case in cases) {
    experiment_path <- case$experiment
    if (!file.exists(experiment_path)) experiment_path <- file.path(dirname(normalizePath(args[[1L]])),basename(experiment_path))
    experiment <- jsonlite::fromJSON(experiment_path,simplifyVector=FALSE)
    folder <- file.path(args[[2L]],case$output)
    dir.create(folder,recursive=TRUE,showWarnings=FALSE)
    start <- proc.time()[["elapsed"]]
    report <- tryCatch({
      key <- digest::digest(experiment$model_code,algo="sha256")
      if (!exists(key,cache,inherits=FALSE)) assign(key,rxode2::rxode2(experiment$model_code),cache)
      answer <- simulate_omex_rxode2(list(model=get(key,cache),experiment=experiment),file.path(folder,"trajectory.csv"))
      answer$provenance$status <- "executed"
      answer$provenance$trajectory_sha256 <- digest::digest(file=file.path(folder,"trajectory.csv"),algo="sha256")
      answer$provenance
    },error=function(e) list(model_id=experiment$model_id,scenario_id=experiment$scenario_id,
                            status="failed",error=conditionMessage(e),archive_sha256=experiment$archive_sha256))
    report$elapsed_seconds <- proc.time()[["elapsed"]]-start
    # The script path comes from Rscript's own command line.
    report$runner_sha256 <- digest::digest(file=sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[[1L]]),algo="sha256")
    jsonlite::write_json(report,file.path(folder,"provenance.json"),auto_unbox=TRUE,pretty=TRUE,digits=NA)
    reports[[length(reports)+1L]] <- report
    jsonlite::write_json(reports,file.path(args[[2L]],"summary.json"),auto_unbox=TRUE,pretty=TRUE,digits=NA)
    cat(experiment$model_id,experiment$scenario_id,report$status,report$error,"\n")
    flush.console()
  }
}
