use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::fmt::{self, Debug};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use fs::{directory, DigestTrie, RelativePath};
use futures::future::{BoxFuture, TryFutureExt};
use futures::FutureExt;
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{headers_to_http_header_map, layered_service, status_to_str, LayeredService};
use hashing::Digest;
use parking_lot::Mutex;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;
use remexec::action_cache_client::ActionCacheClient;
use remexec::{ActionResult, Command, Tree};
use store::{Store, StoreError};
use workunit_store::{
    in_workunit, Level, Metric, ObservationMetric, RunningWorkunit, WorkunitMetadata,
};

use crate::remote::{apply_headers, make_execute_request, populate_fallible_execution_result};
use crate::{
    check_cache_content, CacheContentBehavior, Context, FallibleProcessResultWithPlatform,
    Platform, Process, ProcessCacheScope, ProcessError, ProcessMetadata, ProcessResultSource,
};
use tonic::{Code, Request, Status};

#[derive(Clone, Copy, Debug, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum RemoteCacheWarningsBehavior {
    Ignore,
    FirstOnly,
    Backoff,
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
    inner: Arc<dyn crate::CommandRunner>,
    metadata: ProcessMetadata,
    executor: task_executor::Executor,
    store: Store,
    action_cache_client: Arc<ActionCacheClient<LayeredService>>,
    platform: Platform,
    cache_read: bool,
    cache_write: bool,
    cache_content_behavior: CacheContentBehavior,
    warnings_behavior: RemoteCacheWarningsBehavior,
    read_errors_counter: Arc<Mutex<BTreeMap<String, usize>>>,
    write_errors_counter: Arc<Mutex<BTreeMap<String, usize>>>,
    read_timeout: Duration,
}

impl CommandRunner {
    pub fn new(
        inner: Arc<dyn crate::CommandRunner>,
        metadata: ProcessMetadata,
        executor: task_executor::Executor,
        store: Store,
        action_cache_address: &str,
        root_ca_certs: Option<Vec<u8>>,
        mut headers: BTreeMap<String, String>,
        platform: Platform,
        cache_read: bool,
        cache_write: bool,
        warnings_behavior: RemoteCacheWarningsBehavior,
        cache_content_behavior: CacheContentBehavior,
        concurrency_limit: usize,
        read_timeout: Duration,
    ) -> Result<Self, String> {
        let tls_client_config = if action_cache_address.starts_with("https://") {
            Some(grpc_util::tls::Config::new_without_mtls(root_ca_certs).try_into()?)
        } else {
            None
        };

        let endpoint = grpc_util::create_endpoint(
            action_cache_address,
            tls_client_config.as_ref(),
            &mut headers,
        )?;
        let http_headers = headers_to_http_header_map(&headers)?;
        let channel = layered_service(
            tonic::transport::Channel::balance_list(vec![endpoint].into_iter()),
            concurrency_limit,
            http_headers,
        );
        let action_cache_client = Arc::new(ActionCacheClient::new(channel));

        Ok(CommandRunner {
            inner,
            metadata,
            executor,
            store,
            action_cache_client,
            platform,
            cache_read,
            cache_write,
            cache_content_behavior,
            warnings_behavior,
            read_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
            write_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
            read_timeout,
        })
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
            Some(directory::Entry::Directory(d)) => d.tree(),
            None => return Ok(None),
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
        sub_trie.walk(&mut |_, entry| match entry {
            directory::Entry::File(f) => file_digests.push(f.digest()),
            directory::Entry::Directory(_) => {}
        });

        Ok(Some((tree, file_digests)))
    }

    pub(crate) fn extract_output_file(
        root_trie: &DigestTrie,
        file_path: &str,
    ) -> Result<Option<remexec::OutputFile>, String> {
        match root_trie.entry(&RelativePath::new(file_path)?)? {
            Some(directory::Entry::File(f)) => {
                let output_file = remexec::OutputFile {
                    digest: Some(f.digest().into()),
                    path: file_path.to_owned(),
                    is_executable: f.is_executable(),
                    ..remexec::OutputFile::default()
                };
                Ok(Some(output_file))
            }
            None => Ok(None),
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
                &self.metadata,
                self.platform,
                &context,
                self.action_cache_client.clone(),
                self.store.clone(),
                self.cache_content_behavior,
                self.read_timeout,
            )
            .await;
            match response {
                Ok(cached_response_opt) => {
                    match &cached_response_opt {
                        Some(cached_response) => {
                            log::debug!(
                                "remote cache hit for: {:?} digest={:?} response={:?}",
                                request.description,
                                action_digest,
                                cached_response
                            );
                        }
                        None => {
                            log::debug!(
                                "remote cache miss for: {:?} digest={:?}",
                                request.description,
                                action_digest
                            );
                        }
                    }

                    cached_response_opt
                }
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
        local_execution_future: BoxFuture<
            '_,
            Result<FallibleProcessResultWithPlatform, ProcessError>,
        >,
    ) -> Result<(FallibleProcessResultWithPlatform, bool), ProcessError> {
        if let Some(cached_response) = cache_result {
            let lookup_elapsed = cache_lookup_start.elapsed();
            workunit.increment_counter(Metric::RemoteCacheSpeculationRemoteCompletedFirst, 1);
            if let Some(time_saved) = cached_response
                .metadata
                .time_saved_from_cache(lookup_elapsed)
            {
                let time_saved = time_saved.as_millis() as u64;
                workunit.increment_counter(Metric::RemoteCacheTotalTimeSavedMs, time_saved);
                workunit.record_observation(ObservationMetric::RemoteCacheTimeSavedMs, time_saved);
            }
            // When we successfully use the cache, we change the description and increase the level
            // (but not so much that it will be logged by default).
            workunit.update_metadata(|initial| {
                initial.map(|(initial, _)| {
                    (
                        WorkunitMetadata {
                            desc: initial.desc.as_ref().map(|desc| format!("Hit: {}", desc)),
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
        metadata: &ProcessMetadata,
        command: &Command,
        action_digest: Digest,
        command_digest: Digest,
    ) -> Result<(), StoreError> {
        // Upload the Action and Command, but not the input files. See #12432.
        // Assumption: The Action and Command have already been stored locally.
        crate::remote::ensure_action_uploaded(&self.store, command_digest, action_digest, None)
            .await?;

        // Create an ActionResult from the process result.
        let (action_result, digests_for_action_result) = self
            .make_action_result(command, result, &self.store)
            .await?;

        // Ensure that all digests referenced by directly and indirectly by the ActionResult
        // have been uploaded to the remote cache.
        self.store
            .ensure_remote_has_recursive(digests_for_action_result)
            .await?;

        let client = self.action_cache_client.as_ref().clone();
        retry_call(
            client,
            move |mut client| {
                let update_action_cache_request = remexec::UpdateActionResultRequest {
                    instance_name: metadata
                        .instance_name
                        .as_ref()
                        .cloned()
                        .unwrap_or_else(|| "".to_owned()),
                    action_digest: Some(action_digest.into()),
                    action_result: Some(action_result.clone()),
                    ..remexec::UpdateActionResultRequest::default()
                };

                async move {
                    client
                        .update_action_result(update_action_cache_request)
                        .await
                }
            },
            status_is_retryable,
        )
        .await
        .map_err(status_to_str)?;

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
        let log_msg = format!(
            "Failed to {} remote cache ({} occurrences so far): {}",
            failure_desc, err_count, err
        );
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
impl crate::CommandRunner for CommandRunner {
    async fn run(
        &self,
        context: Context,
        workunit: &mut RunningWorkunit,
        request: Process,
    ) -> Result<FallibleProcessResultWithPlatform, ProcessError> {
        let cache_lookup_start = Instant::now();
        // Construct the REv2 ExecuteRequest and related data for this execution request.
        let (action, command, _execute_request) =
            make_execute_request(&request, self.metadata.clone())?;
        let write_failures_to_cache = request.cache_scope == ProcessCacheScope::Always;

        // Ensure the action and command are stored locally.
        let (command_digest, action_digest) =
            crate::remote::ensure_action_stored_locally(&self.store, &command, &action).await?;

        let (result, hit_cache) = if self.cache_read {
            self.speculate_read_action_cache(
                context.clone(),
                cache_lookup_start,
                action_digest,
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

        if !hit_cache && (result.exit_code == 0 || write_failures_to_cache) && self.cache_write {
            let command_runner = self.clone();
            let result = result.clone();
            let _write_join = self.executor.spawn(in_workunit!(
                "remote_cache_write",
                Level::Trace,
                |workunit| async move {
                    workunit.increment_counter(Metric::RemoteCacheWriteAttempts, 1);
                    let write_result = command_runner
                        .update_action_cache(
                            &result,
                            &command_runner.metadata,
                            &command,
                            action_digest,
                            command_digest,
                        )
                        .await;
                    match write_result {
                        Ok(_) => workunit.increment_counter(Metric::RemoteCacheWriteSuccesses, 1),
                        Err(err) => {
                            command_runner
                                .log_cache_error(err.to_string(), CacheErrorType::WriteError);
                            workunit.increment_counter(Metric::RemoteCacheWriteErrors, 1);
                        }
                    };
                }
                // NB: We must box the future to avoid a stack overflow.
                .boxed()
            ));
        }

        Ok(result)
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
    metadata: &ProcessMetadata,
    platform: Platform,
    context: &Context,
    action_cache_client: Arc<ActionCacheClient<LayeredService>>,
    store: Store,
    cache_content_behavior: CacheContentBehavior,
    timeout_duration: Duration,
) -> Result<Option<FallibleProcessResultWithPlatform>, ProcessError> {
    in_workunit!(
        "check_action_cache",
        Level::Debug,
        desc = Some(format!("Remote cache lookup for: {}", command_description)),
        |workunit| async move {
            workunit.increment_counter(Metric::RemoteCacheRequests, 1);

            let start = Instant::now();
            let client = action_cache_client.as_ref().clone();
            let response = retry_call(
                client,
                move |mut client| {
                    let request = remexec::GetActionResultRequest {
                        action_digest: Some(action_digest.into()),
                        instance_name: metadata.instance_name.as_ref().cloned().unwrap_or_default(),
                        ..remexec::GetActionResultRequest::default()
                    };
                    let request = apply_headers(Request::new(request), &context.build_id);
                    async move {
                        let lookup_fut = client.get_action_result(request);
                        let timeout_fut = tokio::time::timeout(timeout_duration, lookup_fut);
                        timeout_fut
                            .await
                            .unwrap_or_else(|_| Err(Status::unavailable("Pants client timeout")))
                    }
                },
                status_is_retryable,
            )
            .and_then(|action_result| async move {
                let action_result = action_result.into_inner();
                let response = populate_fallible_execution_result(
                    store.clone(),
                    context.run_id,
                    &action_result,
                    platform,
                    false,
                    ProcessResultSource::HitRemotely,
                )
                .await
                .map_err(|e| {
                    Status::unavailable(format!("Output roots could not be loaded: {e}"))
                })?;

                let cache_content_valid =
                    check_cache_content(&response, &store, cache_content_behavior)
                        .await
                        .map_err(|e| {
                            Status::unavailable(format!(
                                "Output content could not be validated: {e}"
                            ))
                        })?;

                if cache_content_valid {
                    Ok(response)
                } else {
                    Err(Status::not_found(""))
                }
            })
            .await;

            workunit.record_observation(
                ObservationMetric::RemoteCacheGetActionResultTimeMicros,
                start.elapsed().as_micros() as u64,
            );

            match response {
                Ok(response) => {
                    workunit.increment_counter(Metric::RemoteCacheRequestsCached, 1);
                    Ok(Some(response))
                }
                Err(status) => match status.code() {
                    Code::NotFound => {
                        workunit.increment_counter(Metric::RemoteCacheRequestsUncached, 1);
                        Ok(None)
                    }
                    _ => {
                        workunit.increment_counter(Metric::RemoteCacheReadErrors, 1);
                        // TODO: Ensure that we're catching missing digests.
                        Err(status_to_str(status).into())
                    }
                },
            }
        }
    )
    .await
}
