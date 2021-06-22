use std::collections::{BTreeMap, HashSet, VecDeque};
use std::ffi::OsString;
use std::path::Component;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::require_digest;
use fs::RelativePath;
use futures::future::BoxFuture;
use futures::FutureExt;
use grpc_util::{headers_to_interceptor_fn, retry::retry_call, status_to_str};
use hashing::Digest;
use parking_lot::Mutex;
use remexec::action_cache_client::ActionCacheClient;
use remexec::{ActionResult, Command, FileNode, Tree};
use store::Store;
use tonic::transport::Channel;
use workunit_store::{in_workunit, Level, Metric, ObservationMetric, WorkunitMetadata};

use crate::remote::make_execute_request;
use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, Process,
  ProcessMetadata, RemoteCacheWarningsBehavior,
};
use grpc_util::retry::status_is_retryable;

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
  underlying: Arc<dyn crate::CommandRunner>,
  metadata: ProcessMetadata,
  executor: task_executor::Executor,
  store: Store,
  action_cache_client: Arc<ActionCacheClient<Channel>>,
  headers: BTreeMap<String, String>,
  platform: Platform,
  cache_read: bool,
  cache_write: bool,
  eager_fetch: bool,
  warnings_behavior: RemoteCacheWarningsBehavior,
  read_errors_counter: Arc<Mutex<BTreeMap<String, usize>>>,
  write_errors_counter: Arc<Mutex<BTreeMap<String, usize>>>,
}

impl CommandRunner {
  pub fn new(
    underlying: Arc<dyn crate::CommandRunner>,
    metadata: ProcessMetadata,
    executor: task_executor::Executor,
    store: Store,
    action_cache_address: &str,
    root_ca_certs: Option<Vec<u8>>,
    headers: BTreeMap<String, String>,
    platform: Platform,
    cache_read: bool,
    cache_write: bool,
    warnings_behavior: RemoteCacheWarningsBehavior,
    eager_fetch: bool,
  ) -> Result<Self, String> {
    let tls_client_config = if action_cache_address.starts_with("https://") {
      Some(grpc_util::create_tls_config(root_ca_certs)?)
    } else {
      None
    };

    let endpoint = grpc_util::create_endpoint(&action_cache_address, tls_client_config.as_ref())?;
    let channel = tonic::transport::Channel::balance_list(vec![endpoint].into_iter());
    let action_cache_client = Arc::new(if headers.is_empty() {
      ActionCacheClient::new(channel)
    } else {
      ActionCacheClient::with_interceptor(channel, headers_to_interceptor_fn(&headers)?)
    });

    Ok(CommandRunner {
      underlying,
      metadata,
      executor,
      store,
      action_cache_client,
      headers,
      platform,
      cache_read,
      cache_write,
      eager_fetch,
      warnings_behavior,
      read_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
      write_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
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
  /// If the output directory does not exist, then returns Ok(None).
  pub(crate) async fn make_tree_for_output_directory(
    root_directory_digest: Digest,
    directory_path: RelativePath,
    store: &Store,
  ) -> Result<Option<Tree>, String> {
    // Traverse down from the root directory digest to find the directory digest for
    // the output directory.
    let mut current_directory_digest = root_directory_digest;
    for next_path_component in directory_path.as_ref().components() {
      let next_name = match next_path_component {
        Component::Normal(name) => name
          .to_str()
          .ok_or_else(|| format!("unable to convert '{:?}' to string", name))?,
        _ => return Ok(None),
      };

      // Load the Directory proto corresponding to `current_directory_digest`.
      let current_directory = match store.load_directory(current_directory_digest).await? {
        Some((dir, _)) => dir,
        None => {
          return Err(format!(
            "Directory digest {:?} was referenced in output, but was not found in store.",
            current_directory_digest
          ))
        }
      };

      // Scan the current directory for the current path component.
      let dir_node = match current_directory
        .directories
        .iter()
        .find(|dn| dn.name == next_name)
      {
        Some(dn) => dn,
        None => return Ok(None),
      };

      // Set the current directory digest to be the digest in the DirectoryNode just found.
      // If there are more path components, then the search will continue there.
      // Otherwise, if this loop ends then the final Directory digest has been found.
      current_directory_digest = require_digest(dir_node.digest.as_ref())?;
    }

    // At this point, `current_directory_digest` holds the digest of the output directory.
    // This will be the root of the Tree. Add it to a queue of digests to traverse.
    let mut tree = Tree::default();

    let mut digest_queue = VecDeque::new();
    digest_queue.push_back(current_directory_digest);

    while let Some(directory_digest) = digest_queue.pop_front() {
      let directory = match store.load_directory(directory_digest).await? {
        Some((dir, _)) => dir,
        None => {
          return Err(format!(
            "illegal state: directory for digest {:?} did not exist locally",
            &current_directory_digest
          ))
        }
      };

      // Add all of the digests for subdirectories into the queue so they are processed
      // in future iterations of the loop.
      for subdirectory_node in &directory.directories {
        let subdirectory_digest = require_digest(subdirectory_node.digest.as_ref())?;
        digest_queue.push_back(subdirectory_digest);
      }

      // Store this directory either as the `root` or one of the `children` if not the root.
      if directory_digest == current_directory_digest {
        tree.root = Some(directory);
      } else {
        tree.children.push(directory)
      }
    }

    Ok(Some(tree))
  }

  pub(crate) async fn extract_output_file(
    root_directory_digest: Digest,
    file_path: RelativePath,
    store: &Store,
  ) -> Result<Option<FileNode>, String> {
    // Traverse down from the root directory digest to find the directory digest for
    // the output directory.
    let mut current_directory_digest = root_directory_digest;
    let parent_path = file_path.as_ref().parent();
    let components_opt = parent_path.map(|x| x.components());
    if let Some(components) = components_opt {
      for next_path_component in components {
        let next_name = match next_path_component {
          Component::Normal(name) => name
            .to_str()
            .ok_or_else(|| format!("unable to convert '{:?}' to string", name))?,
          _ => return Ok(None),
        };

        // Load the Directory proto corresponding to `current_directory_digest`.
        let current_directory = match store.load_directory(current_directory_digest).await? {
          Some((dir, _)) => dir,
          None => {
            return Err(format!(
              "Directory digest {:?} was referenced in output, but was not found in store.",
              current_directory_digest
            ))
          }
        };

        // Scan the current directory for the current path component.
        let dir_node = match current_directory
          .directories
          .iter()
          .find(|dn| dn.name == next_name)
        {
          Some(dn) => dn,
          None => return Ok(None),
        };

        // Set the current directory digest to be the digest in the DirectoryNode just found.
        // If there are more path components, then the search will continue there.
        // Otherwise, if this loop ends then the final Directory digest has been found.
        current_directory_digest = require_digest(dir_node.digest.as_ref())?;
      }
    }

    // Load the final directory.
    let directory = match store.load_directory(current_directory_digest).await? {
      Some((dir, _)) => dir,
      None => return Ok(None),
    };

    // Search for the file.
    let file_base_name = file_path.as_ref().file_name().unwrap();
    Ok(
      directory
        .files
        .iter()
        .find(|node| {
          let name = OsString::from(&node.name);
          name == file_base_name
        })
        .cloned(),
    )
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
  ) -> Result<(ActionResult, Vec<Digest>), String> {
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
      let tree = match Self::make_tree_for_output_directory(
        result.output_directory,
        RelativePath::new(output_directory).unwrap(),
        store,
      )
      .await?
      {
        Some(t) => t,
        None => continue,
      };

      let tree_digest = crate::remote::store_proto_locally(&self.store, &tree).await?;
      digests.insert(tree_digest);

      action_result
        .output_directories
        .push(remexec::OutputDirectory {
          path: output_directory.to_owned(),
          tree_digest: Some(tree_digest.into()),
        });
    }

    for output_file in &command.output_files {
      let file_node = match Self::extract_output_file(
        result.output_directory,
        RelativePath::new(output_file).unwrap(),
        store,
      )
      .await?
      {
        Some(node) => node,
        None => continue,
      };

      let digest = require_digest(file_node.digest.as_ref())?;
      digests.insert(digest);

      action_result.output_files.push({
        remexec::OutputFile {
          digest: Some(digest.into()),
          path: output_file.to_owned(),
          is_executable: file_node.is_executable,
          ..remexec::OutputFile::default()
        }
      })
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
    mut local_execution_future: BoxFuture<'_, Result<FallibleProcessResultWithPlatform, String>>,
  ) -> Result<(FallibleProcessResultWithPlatform, bool), String> {
    // A future to read from the cache and log the results accordingly.
    let cache_read_future = async {
      let response = crate::remote::check_action_cache(
        action_digest,
        &self.metadata,
        self.platform,
        &context,
        self.action_cache_client.clone(),
        self.store.clone(),
        self.eager_fetch,
      )
      .await;
      match response {
        Ok(cached_response_opt) => {
          log::debug!(
            "remote cache response: digest={:?}: {:?}",
            action_digest,
            cached_response_opt
          );
          cached_response_opt
        }
        Err(err) => {
          self.log_cache_error(err, CacheErrorType::ReadError);
          None
        }
      }
    }
    .boxed();

    // We speculate between reading from the remote cache vs. running locally.
    let context2 = context.clone();
    in_workunit!(
      context.workunit_store.clone(),
      "remote_cache_read_speculation".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        ..WorkunitMetadata::default()
      },
      |workunit| async move {
        tokio::select! {
          cache_result = cache_read_future => {
            if let Some(cached_response) = cache_result {
              let lookup_elapsed = cache_lookup_start.elapsed();
              workunit.increment_counter(Metric::RemoteCacheSpeculationRemoteCompletedFirst, 1);
              if let Some(time_saved) = cached_response.metadata.time_saved_from_cache(lookup_elapsed) {
                let time_saved = time_saved.as_millis() as u64;
                workunit.increment_counter(Metric::RemoteCacheTotalTimeSavedMs, time_saved);
                context2
                  .workunit_store
                  .record_observation(ObservationMetric::RemoteCacheTimeSavedMs, time_saved);
                }
              Ok((cached_response, true))
            } else {
              // Note that we don't increment a counter here, as there is nothing of note in this
              // scenario: the remote cache did not save unnecessary local work, nor was the remote
              // trip unusually slow such that local execution was faster.
              local_execution_future.await.map(|res| (res, false))
            }
          }
          local_result = &mut local_execution_future => {
            workunit.increment_counter(Metric::RemoteCacheSpeculationLocalCompletedFirst, 1);
            local_result.map(|res| (res, false))
          }
        }
      }
    ).await
  }

  /// Stores an execution result into the remote Action Cache.
  async fn update_action_cache(
    &self,
    context: &Context,
    request: &Process,
    result: &FallibleProcessResultWithPlatform,
    metadata: &ProcessMetadata,
    command: &Command,
    action_digest: Digest,
    command_digest: Digest,
  ) -> Result<(), String> {
    // Upload the action (and related data, i.e. the embedded command and input files).
    // Assumption: The Action and related data has already been stored locally.
    in_workunit!(
      context.workunit_store.clone(),
      "ensure_action_uploaded".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("ensure action uploaded for {:?}", action_digest)),
        ..WorkunitMetadata::default()
      },
      |_workunit| crate::remote::ensure_action_uploaded(
        &self.store,
        command_digest,
        action_digest,
        request.input_files,
      ),
    )
    .await?;

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

enum CacheErrorType {
  ReadError,
  WriteError,
}

#[async_trait]
impl crate::CommandRunner for CommandRunner {
  async fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let cache_lookup_start = Instant::now();
    // Construct the REv2 ExecuteRequest and related data for this execution request.
    let request = self
      .extract_compatible_request(&req)
      .ok_or_else(|| "No compatible Process found for checking remote cache.".to_owned())?;
    let (action, command, _execute_request) =
      make_execute_request(&request, self.metadata.clone())?;

    // Ensure the action and command are stored locally.
    let command2 = command.clone();
    let (command_digest, action_digest) = in_workunit!(
      context.workunit_store.clone(),
      "ensure_action_stored_locally".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("ensure action stored locally for {:?}", action)),
        ..WorkunitMetadata::default()
      },
      |_workunit| crate::remote::ensure_action_stored_locally(&self.store, &command2, &action),
    )
    .await?;

    let (result, hit_cache) = if self.cache_read {
      self
        .speculate_read_action_cache(
          context.clone(),
          cache_lookup_start,
          action_digest,
          self.underlying.run(req, context.clone()),
        )
        .await?
    } else {
      (self.underlying.run(req, context.clone()).await?, false)
    };

    if !hit_cache && result.exit_code == 0 && self.cache_write {
      // NB: We use a distinct workunit for the start of the cache write so that we guarantee the
      // counter is recorded, given that the cache write is async and may still be executing after
      // the Pants session has finished and workunits are no longer processed.
      //
      // TODO(#11688): remove this workunit once we have tailing tasks.
      in_workunit!(
        context.workunit_store.clone(),
        "remote_cache_write_setup".to_owned(),
        WorkunitMetadata {
          level: Level::Trace,
          ..WorkunitMetadata::default()
        },
        |workunit| async move {
          workunit.increment_counter(Metric::RemoteCacheWriteAttempts, 1);
        }
      )
      .await;
      let command_runner = self.clone();
      let result = result.clone();
      let context2 = context.clone();
      // NB: We use `TaskExecutor::spawn` instead of `tokio::spawn` to ensure logging still works.
      let _write_join = self.executor.spawn(in_workunit!(
        context.workunit_store,
        "remote_cache_write".to_owned(),
        WorkunitMetadata {
          level: Level::Trace,
          ..WorkunitMetadata::default()
        },
        |workunit| async move {
          let write_result = command_runner
            .update_action_cache(
              &context2,
              &request,
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
              command_runner.log_cache_error(err, CacheErrorType::WriteError);
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

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    self.underlying.extract_compatible_request(req)
  }
}
