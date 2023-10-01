// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashSet};
use std::fmt::{self, Debug};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use fs::{directory, DigestTrie, RelativePath, SymlinkBehavior};
use futures::future::{BoxFuture, TryFutureExt};
use futures::FutureExt;
use grpc_util::tls;
use hashing::Digest;
use parking_lot::Mutex;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;
use remexec::{ActionResult, Command, Tree};
use remote_provider::{ActionCacheProvider, REAPI_ADDRESS_SCHEMAS};
use store::{RemoteOptions, Store, StoreError};
use workunit_store::{
  in_workunit, Level, Metric, ObservationMetric, RunningWorkunit, WorkunitMetadata,
};

use process_execution::{
  check_cache_content, populate_fallible_execution_result, CacheContentBehavior, Context,
  FallibleProcessResultWithPlatform, Process, ProcessCacheScope, ProcessError,
  ProcessExecutionEnvironment, ProcessResultSource,
};
use process_execution::{make_execute_request, EntireExecuteRequest};

mod reapi;
#[cfg(test)]
mod reapi_tests;

#[derive(Clone, Copy, Debug, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum RemoteCacheWarningsBehavior {
  Ignore,
  FirstOnly,
  Backoff,
}

#[derive(Clone)]
pub struct RemoteCacheProviderOptions {
  // TODO: this is currently framed for the REAPI provider, with some options used by others, would
  // be good to generalise
  // TODO: this is structurally very similar to `RemoteOptions`: maybe they should be the same? (see
  // comment in `choose_provider` too)
  pub instance_name: Option<String>,
  pub action_cache_address: String,
  pub root_ca_certs: Option<Vec<u8>>,
  pub mtls_data: Option<(Vec<u8>, Vec<u8>)>,
  pub headers: BTreeMap<String, String>,
  pub concurrency_limit: usize,
  pub rpc_timeout: Duration,
}

async fn choose_provider(
  options: RemoteCacheProviderOptions,
) -> Result<Arc<dyn ActionCacheProvider>, String> {
  let address = options.action_cache_address.clone();

  // TODO: we shouldn't need to gin up a whole copy of this struct; it'd be better to have the two
  // set of remoting options managed together.
  let remote_options = RemoteOptions {
    cas_address: address.clone(),
    instance_name: options.instance_name.clone(),
    headers: options.headers.clone(),
    tls_config: tls::Config::new(options.root_ca_certs.clone(), options.mtls_data.clone())?,
    rpc_timeout: options.rpc_timeout,
    rpc_concurrency_limit: options.concurrency_limit,
    // TODO: these should either be passed through or not synthesized here
    chunk_size_bytes: 0,
    rpc_retries: 0,
    capabilities_cell_opt: None,
    batch_api_size_limit: 0,
  };

  if REAPI_ADDRESS_SCHEMAS.iter().any(|s| address.starts_with(s)) {
    Ok(Arc::new(reapi::Provider::new(options).await?))
  } else if let Some(path) = address.strip_prefix("file://") {
    // It's a bit weird to support local "file://" for a 'remote' store... but this is handy for
    // testing.
    Ok(Arc::new(remote_provider_opendal::Provider::fs(
      path,
      "action-cache".to_owned(),
      remote_options,
    )?))
  } else if let Some(url) = address.strip_prefix("github-actions-cache+") {
    // This is relying on python validating that it was set as `github-actions-cache+https://...` so
    // incorrect values could easily slip through here and cause downstream confusion. We're
    // intending to change the approach (https://github.com/pantsbuild/pants/issues/19902) so this
    // is tolerable for now.
    Ok(Arc::new(
      remote_provider_opendal::Provider::github_actions_cache(
        url,
        "action-cache".to_owned(),
        remote_options,
      )?,
    ))
  } else {
    Err(format!(
      "Cannot initialise remote action cache provider with address {address}, as the scheme is not supported",
    ))
  }
}

pub struct RemoteCacheRunnerOptions {
  pub inner: Arc<dyn process_execution::CommandRunner>,
  pub instance_name: Option<String>,
  pub process_cache_namespace: Option<String>,
  pub executor: task_executor::Executor,
  pub store: Store,
  pub cache_read: bool,
  pub cache_write: bool,
  pub warnings_behavior: RemoteCacheWarningsBehavior,
  pub cache_content_behavior: CacheContentBehavior,
  pub append_only_caches_base_path: Option<String>,
}

/// This `CommandRunner` implementation caches results remotely using the Action Cache service
/// of the Remote Execution API.
///
/// This runner expects to sit between the local cache CommandRunner and the CommandRunner
/// that is actually executing the Process. Thus, the local cache will be checked first,
/// then the remote cache, and then execution (local or remote) as necessary if neither cache
/// has a hit. On the way back out of the stack, the result will be stored remotely and
/// then locally.
#[derive(Clone)]
pub struct CommandRunner {
  inner: Arc<dyn process_execution::CommandRunner>,
  instance_name: Option<String>,
  process_cache_namespace: Option<String>,
  append_only_caches_base_path: Option<String>,
  executor: task_executor::Executor,
  store: Store,
  provider: Arc<dyn ActionCacheProvider>,
  cache_read: bool,
  cache_write: bool,
  cache_content_behavior: CacheContentBehavior,
  warnings_behavior: RemoteCacheWarningsBehavior,
  read_errors_counter: Arc<Mutex<BTreeMap<String, usize>>>,
  write_errors_counter: Arc<Mutex<BTreeMap<String, usize>>>,
}

impl CommandRunner {
  pub fn new(
    RemoteCacheRunnerOptions {
      inner,
      instance_name,
      process_cache_namespace,
      executor,
      store,
      cache_read,
      cache_write,
      warnings_behavior,
      cache_content_behavior,
      append_only_caches_base_path,
    }: RemoteCacheRunnerOptions,
    provider: Arc<dyn ActionCacheProvider + 'static>,
  ) -> Self {
    CommandRunner {
      inner,
      instance_name,
      process_cache_namespace,
      append_only_caches_base_path,
      executor,
      store,
      provider,
      cache_read,
      cache_write,
      cache_content_behavior,
      warnings_behavior,
      read_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
      write_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
    }
  }

  pub async fn from_provider_options(
    runner_options: RemoteCacheRunnerOptions,
    provider_options: RemoteCacheProviderOptions,
  ) -> Result<Self, String> {
    let provider = choose_provider(provider_options).await?;
    Ok(Self::new(runner_options, provider))
  }

  /// Create a REAPI `Tree` protobuf for an output directory by traversing down from a Pants
  /// merged final output directory to find the specific path to extract. (REAPI requires
  /// output directories to be stored as `Tree` protos that contain all of the `Directory`
  /// protos that constitute the directory tree.)
  ///
  /// Note that the Tree does not include the directory_path as a prefix, per REAPI. This path
  /// gets stored on the OutputDirectory proto.
  ///
  /// Returns the created Tree and any File Digests referenced within it. If the output directory
  /// does not exist, then returns Ok(None).
  pub(crate) fn make_tree_for_output_directory(
    root_trie: &DigestTrie,
    directory_path: RelativePath,
  ) -> Result<Option<(Tree, Vec<Digest>)>, String> {
    let sub_trie = match root_trie.entry(&directory_path)? {
      None => return Ok(None),
      Some(directory::Entry::Directory(d)) => d.tree(),
      Some(directory::Entry::Symlink(_)) => {
        return Err(format!(
          "Declared output directory path {directory_path:?} in output \
           digest {trie_digest:?} contained a symlink instead.",
          trie_digest = root_trie.compute_root_digest(),
        ))
      }
      Some(directory::Entry::File(_)) => {
        return Err(format!(
          "Declared output directory path {directory_path:?} in output \
           digest {trie_digest:?} contained a file instead.",
          trie_digest = root_trie.compute_root_digest(),
        ))
      }
    };

    let tree = sub_trie.into();
    let mut file_digests = Vec::new();
    sub_trie.walk(SymlinkBehavior::Aware, &mut |_, entry| match entry {
      directory::Entry::File(f) => file_digests.push(f.digest()),
      directory::Entry::Symlink(_) => (),
      directory::Entry::Directory(_) => {}
    });

    Ok(Some((tree, file_digests)))
  }

  pub(crate) fn extract_output_file(
    root_trie: &DigestTrie,
    file_path: &str,
  ) -> Result<Option<remexec::OutputFile>, String> {
    match root_trie.entry(&RelativePath::new(file_path)?)? {
      None => Ok(None),
      Some(directory::Entry::File(f)) => {
        let output_file = remexec::OutputFile {
          digest: Some(f.digest().into()),
          path: file_path.to_owned(),
          is_executable: f.is_executable(),
          ..remexec::OutputFile::default()
        };
        Ok(Some(output_file))
      }
      Some(directory::Entry::Symlink(_)) => Err(format!(
        "Declared output file path {file_path:?} in output \
           digest {trie_digest:?} contained a symlink instead.",
        trie_digest = root_trie.compute_root_digest(),
      )),
      Some(directory::Entry::Directory(_)) => Err(format!(
        "Declared output file path {file_path:?} in output \
           digest {trie_digest:?} contained a directory instead.",
        trie_digest = root_trie.compute_root_digest(),
      )),
    }
  }

  /// Converts a REAPI `Command` and a `FallibleProcessResultWithPlatform` produced from executing
  /// that Command into a REAPI `ActionResult` suitable for upload to the REAPI Action Cache.
  ///
  /// This function also returns a vector of all `Digest`s referenced directly and indirectly by
  /// the `ActionResult` suitable for passing to `Store::ensure_remote_has_recursive`. (The
  /// digests may include both File and Tree digests.)
  pub(crate) async fn make_action_result(
    &self,
    command: &Command,
    result: &FallibleProcessResultWithPlatform,
    store: &Store,
  ) -> Result<(ActionResult, Vec<Digest>), StoreError> {
    let output_trie = store
      .load_digest_trie(result.output_directory.clone())
      .await?;

    // Keep track of digests that need to be uploaded.
    let mut digests = HashSet::new();

    let mut action_result = ActionResult {
      exit_code: result.exit_code,
      stdout_digest: Some(result.stdout_digest.into()),
      stderr_digest: Some(result.stderr_digest.into()),
      execution_metadata: Some(result.metadata.clone().into()),
      ..ActionResult::default()
    };

    digests.insert(result.stdout_digest);
    digests.insert(result.stderr_digest);

    for output_directory in &command.output_directories {
      let (tree, file_digests) = match Self::make_tree_for_output_directory(
        &output_trie,
        RelativePath::new(output_directory).unwrap(),
      )? {
        Some(res) => res,
        None => continue,
      };

      let tree_digest = crate::remote::store_proto_locally(&self.store, &tree).await?;
      digests.insert(tree_digest);
      digests.extend(file_digests);

      action_result
        .output_directories
        .push(remexec::OutputDirectory {
          path: output_directory.to_owned(),
          tree_digest: Some(tree_digest.into()),
          is_topologically_sorted: false,
        });
    }

    for output_file_path in &command.output_files {
      let output_file = match Self::extract_output_file(&output_trie, output_file_path)? {
        Some(output_file) => output_file,
        None => continue,
      };

      digests.insert(require_digest(output_file.digest.as_ref())?);
      action_result.output_files.push(output_file);
    }

    Ok((action_result, digests.into_iter().collect::<Vec<_>>()))
  }

  ///
  /// Races the given local execution future against an attempt to look up the result in the cache.
  ///
  /// Returns a result that indicates whether we used the cache so that we can skip cache writes if
  /// so.
  ///
  async fn speculate_read_action_cache(
    &self,
    context: Context,
    cache_lookup_start: Instant,
    action_digest: Digest,
    failures_cached: bool,
    request: &Process,
    mut local_execution_future: BoxFuture<
      '_,
      Result<FallibleProcessResultWithPlatform, ProcessError>,
    >,
  ) -> Result<(FallibleProcessResultWithPlatform, bool), ProcessError> {
    // A future to read from the cache and log the results accordingly.
    let mut cache_read_future = async {
      let response = check_action_cache(
        action_digest,
        &request.description,
        request.execution_environment.clone(),
        &context,
        self.provider.clone(),
        self.store.clone(),
        self.cache_content_behavior,
      )
      .await;
      match response {
        Ok(cached_response_opt) => match &cached_response_opt {
          Some(cached_response) if cached_response.exit_code == 0 || failures_cached => {
            log::debug!(
              "remote cache hit for: {:?} digest={:?} response={:?}",
              request.description,
              action_digest,
              cached_response
            );
            cached_response_opt
          }
          _ => {
            log::debug!(
              "remote cache miss for: {:?} digest={:?}",
              request.description,
              action_digest
            );
            None
          }
        },
        Err(err) => {
          self.log_cache_error(err.to_string(), CacheErrorType::ReadError);
          None
        }
      }
    }
    .boxed();

    // We speculate between reading from the remote cache vs. running locally.
    in_workunit!(
      "remote_cache_read_speculation",
      Level::Trace,
      |workunit| async move {
        tokio::select! {
          cache_result = &mut cache_read_future => {
            self.handle_cache_read_completed(workunit, cache_lookup_start, cache_result, local_execution_future).await
          }
          _ = tokio::time::sleep(request.remote_cache_speculation_delay) => {
            tokio::select! {
              cache_result = cache_read_future => {
                self.handle_cache_read_completed(workunit, cache_lookup_start, cache_result, local_execution_future).await
              }
              local_result = &mut local_execution_future => {
                workunit.increment_counter(Metric::RemoteCacheSpeculationLocalCompletedFirst, 1);
                local_result.map(|res| (res, false))
              }
            }
          }
        }
      }
    ).await
  }

  async fn handle_cache_read_completed(
    &self,
    workunit: &mut RunningWorkunit,
    cache_lookup_start: Instant,
    cache_result: Option<FallibleProcessResultWithPlatform>,
    local_execution_future: BoxFuture<'_, Result<FallibleProcessResultWithPlatform, ProcessError>>,
  ) -> Result<(FallibleProcessResultWithPlatform, bool), ProcessError> {
    if let Some(mut cached_response) = cache_result {
      cached_response
        .metadata
        .update_cache_hit_elapsed(cache_lookup_start.elapsed());
      workunit.increment_counter(Metric::RemoteCacheSpeculationRemoteCompletedFirst, 1);
      if let Some(time_saved) = cached_response.metadata.saved_by_cache {
        let time_saved = std::time::Duration::from(time_saved).as_millis() as u64;
        workunit.increment_counter(Metric::RemoteCacheTotalTimeSavedMs, time_saved);
        workunit.record_observation(ObservationMetric::RemoteCacheTimeSavedMs, time_saved);
      }
      // When we successfully use the cache, we change the description and increase the level
      // (but not so much that it will be logged by default).
      workunit.update_metadata(|initial| {
        initial.map(|(initial, _)| {
          (
            WorkunitMetadata {
              desc: initial.desc.as_ref().map(|desc| format!("Hit: {desc}")),
              ..initial
            },
            Level::Debug,
          )
        })
      });
      Ok((cached_response, true))
    } else {
      // Note that we don't increment a counter here, as there is nothing of note in this
      // scenario: the remote cache did not save unnecessary local work, nor was the remote
      // trip unusually slow such that local execution was faster.
      local_execution_future.await.map(|res| (res, false))
    }
  }

  /// Stores an execution result into the remote Action Cache.
  async fn update_action_cache(
    &self,
    result: &FallibleProcessResultWithPlatform,
    command: &Command,
    action_digest: Digest,
    command_digest: Digest,
  ) -> Result<(), StoreError> {
    // Upload the Action and Command, but not the input files. See #12432.
    // Assumption: The Action and Command have already been stored locally.
    crate::remote::ensure_action_uploaded(&self.store, command_digest, action_digest, None).await?;

    // Create an ActionResult from the process result.
    let (action_result, digests_for_action_result) = self
      .make_action_result(command, result, &self.store)
      .await?;

    // Ensure that all digests referenced by directly and indirectly by the ActionResult
    // have been uploaded to the remote cache.
    self
      .store
      .ensure_remote_has_recursive(digests_for_action_result)
      .await?;

    self
      .provider
      .update_action_result(action_digest, action_result)
      .await?;
    Ok(())
  }

  fn log_cache_error(&self, err: String, err_type: CacheErrorType) {
    let err_count = {
      let mut errors_counter = match err_type {
        CacheErrorType::ReadError => self.read_errors_counter.lock(),
        CacheErrorType::WriteError => self.write_errors_counter.lock(),
      };
      let count = errors_counter.entry(err.clone()).or_insert(0);
      *count += 1;
      *count
    };
    let failure_desc = match err_type {
      CacheErrorType::ReadError => "read from",
      CacheErrorType::WriteError => "write to",
    };
    let log_msg =
      format!("Failed to {failure_desc} remote cache ({err_count} occurrences so far): {err}");
    let log_at_warn = match self.warnings_behavior {
      RemoteCacheWarningsBehavior::Ignore => false,
      RemoteCacheWarningsBehavior::FirstOnly => err_count == 1,
      RemoteCacheWarningsBehavior::Backoff => err_count.is_power_of_two(),
    };
    if log_at_warn {
      log::warn!("{}", log_msg);
    } else {
      log::debug!("{}", log_msg);
    }
  }
}

impl Debug for CommandRunner {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    f.debug_struct("remote_cache::CommandRunner")
      .field("inner", &self.inner)
      .finish_non_exhaustive()
  }
}

enum CacheErrorType {
  ReadError,
  WriteError,
}

#[async_trait]
impl process_execution::CommandRunner for CommandRunner {
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    request: Process,
  ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
    let cache_lookup_start = Instant::now();
    // Construct the REv2 ExecuteRequest and related data for this execution request.
    let EntireExecuteRequest {
      action, command, ..
    } = make_execute_request(
      &request,
      self.instance_name.clone(),
      self.process_cache_namespace.clone(),
      &self.store,
      self
        .append_only_caches_base_path
        .as_ref()
        .map(|s| s.as_ref()),
    )
    .await?;
    let failures_cached = request.cache_scope == ProcessCacheScope::Always;

    // Ensure the action and command are stored locally.
    let (command_digest, action_digest) =
      crate::remote::ensure_action_stored_locally(&self.store, &command, &action).await?;

    let use_remote_cache = request.cache_scope == ProcessCacheScope::Always
      || request.cache_scope == ProcessCacheScope::Successful;

    let (result, hit_cache) = if self.cache_read && use_remote_cache {
      self
        .speculate_read_action_cache(
          context.clone(),
          cache_lookup_start,
          action_digest,
          failures_cached,
          &request.clone(),
          self.inner.run(context.clone(), workunit, request),
        )
        .await?
    } else {
      (
        self.inner.run(context.clone(), workunit, request).await?,
        false,
      )
    };

    if !hit_cache
      && (result.exit_code == 0 || failures_cached)
      && self.cache_write
      && use_remote_cache
    {
      let command_runner = self.clone();
      let result = result.clone();
      let write_fut = in_workunit!("remote_cache_write", Level::Trace, |workunit| async move {
        workunit.increment_counter(Metric::RemoteCacheWriteAttempts, 1);
        let write_result = command_runner
          .update_action_cache(&result, &command, action_digest, command_digest)
          .await;
        match write_result {
          Ok(_) => workunit.increment_counter(Metric::RemoteCacheWriteSuccesses, 1),
          Err(err) => {
            command_runner.log_cache_error(err.to_string(), CacheErrorType::WriteError);
            workunit.increment_counter(Metric::RemoteCacheWriteErrors, 1);
          }
        };
      }
      // NB: We must box the future to avoid a stack overflow.
      .boxed());
      let task_name = format!("remote cache write {action_digest:?}");
      context
        .tail_tasks
        .spawn_on(&task_name, self.executor.handle(), write_fut.boxed());
    }

    Ok(result)
  }

  async fn shutdown(&self) -> Result<(), String> {
    self.inner.shutdown().await
  }
}

/// Check the remote Action Cache for a cached result of running the given `command` and the Action
/// with the given `action_digest`.
///
/// This check is necessary because some REAPI servers do not short-circuit the Execute method
/// by checking the Action Cache (e.g., BuildBarn). Thus, this client must check the cache
/// explicitly in order to avoid duplicating already-cached work. This behavior matches
/// the Bazel RE client.
async fn check_action_cache(
  action_digest: Digest,
  command_description: &str,
  environment: ProcessExecutionEnvironment,
  context: &Context,
  provider: Arc<dyn ActionCacheProvider>,
  store: Store,
  cache_content_behavior: CacheContentBehavior,
) -> Result<Option<FallibleProcessResultWithPlatform>, ProcessError> {
  in_workunit!(
    "check_action_cache",
    Level::Debug,
    desc = Some(format!("Remote cache lookup for: {command_description}")),
    |workunit| async move {
      workunit.increment_counter(Metric::RemoteCacheRequests, 1);

      let start = Instant::now();
      let response = provider
        .get_action_result(action_digest, &context.build_id)
        .and_then(|action_result| async move {
          let Some(action_result) = action_result else {
            return Ok(None);
          };

          let response = populate_fallible_execution_result(
            store.clone(),
            context.run_id,
            &action_result,
            false,
            ProcessResultSource::HitRemotely,
            environment,
          )
          .await
          .map_err(|e| format!("Output roots could not be loaded: {e}"))?;

          let cache_content_valid = check_cache_content(&response, &store, cache_content_behavior)
            .await
            .map_err(|e| format!("Output content could not be validated: {e}"))?;

          if cache_content_valid {
            Ok(Some(response))
          } else {
            Ok(None)
          }
        })
        .await;

      workunit.record_observation(
        ObservationMetric::RemoteCacheGetActionResultTimeMicros,
        start.elapsed().as_micros() as u64,
      );

      let counter = match response {
        Ok(Some(_)) => Metric::RemoteCacheRequestsCached,
        Ok(None) => Metric::RemoteCacheRequestsUncached,
        // TODO: Ensure that we're catching missing digests.
        Err(_) => Metric::RemoteCacheReadErrors,
      };
      workunit.increment_counter(counter, 1);

      response.map_err(ProcessError::from)
    }
  )
  .await
}
