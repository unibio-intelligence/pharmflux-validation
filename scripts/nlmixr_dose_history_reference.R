# Explicit administered-amount reference for deterministic one-person comparisons.
# This is a recorded workaround for rxode2 infusion podo(), not an upstream patch.
prepare_administered_amount_history <- function(ui, dataset) {
  if (!is.data.frame(dataset) || !all(c('TIME','EVID','AMT','CMT') %in% names(dataset))) stop('missing event columns')
  if ('ID' %in% names(dataset) && length(unique(dataset$ID))!=1L) stop('require one individual')
  if (is.unsorted(dataset$TIME)) stop('events must be in chronological order')
  current <- 0
  history <- numeric(nrow(dataset))
  for (i in seq_len(nrow(dataset))) {
    if (dataset$EVID[i]==1) {
      if (!tolower(as.character(dataset$CMT[i])) %in% c('depot','1')) stop('require explicit depot administrations')
      if (!is.finite(dataset$AMT[i]) || dataset$AMT[i]<0) stop('require finite nonnegative administered amount')
      if (i>1L && any(dataset$EVID[seq_len(i-1L)]==1 & dataset$TIME[seq_len(i-1L)]==dataset$TIME[i])) stop('simultaneous administrations require separate adjudication')
      current <- dataset$AMT[i]
    } else if (dataset$EVID[i]!=0) stop('resets and other event types are not supported by this reference')
    history[i] <- current
  }
  if ('comparison_administered_amount_depot' %in% names(dataset) &&
      any(dataset$comparison_administered_amount_depot!=history)) stop('declared dose history disagrees with raw AMT')
  dataset$comparison_administered_amount_depot <- history
  fun <- ui$fun
  original <- paste(deparse(body(fun),width.cutoff=500L),collapse='\n')
  replaced <- 0L
  rewrite <- function(node) {
    if (!is.call(node)) return(node)
    if (identical(node[[1L]],as.name('podo'))) {
      if (length(node)!=2L || !identical(node[[2L]],as.name('depot'))) stop('unsupported history target')
      replaced <<- replaced+1L
      return(as.name('comparison_administered_amount_depot'))
    }
    for (i in seq_along(node)) node[i] <- list(rewrite(node[[i]]))
    node
  }
  body(fun) <- rewrite(body(fun))
  if (replaced==0L) stop('model has no explicit depot podo() use')
  corrected <- paste(deparse(body(fun),width.cutoff=500L),collapse='\n')
  list(object=rxode2::rxode2(fun),events=dataset,correction=list(
    kind='explicit_administered_amount_for_podo',
    scope='Raw administered AMT history; original upstream intrinsic result remains retained',
    original_function_sha256=digest::digest(original,algo='sha256',serialize=FALSE),
    corrected_function_sha256=digest::digest(corrected,algo='sha256',serialize=FALSE),
    event_semantics='One individual; chronological depot events; observation covariates follow preceding administrations; simultaneous doses and resets rejected'))
}
