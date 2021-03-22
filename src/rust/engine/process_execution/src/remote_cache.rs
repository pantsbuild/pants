use std::collections::{BTreeMap, HashSet, VecDeque};
use std::ffi::OsString;
use std::path::Component;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::require_digest;
use fs::RelativePath;
use futures::FutureExt;
use grpc_util::headers_to_interceptor_fn;
use hashing::Digest;
use parking_lot::Mutex;
use remexec::action_cache_client::ActionCacheClient;
use remexec::{ActionResult, Command, FileNode, Tree};
use store::Store;
use tonic::transport::Channel;
use workunit_store::{with_workunit, Level, Metric, ObservationMetric, WorkunitMetadata};

use crate::remote::make_execute_request;
use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, Process,
  ProcessMetadata,
};

/// Every n times, log a particular remote cache error at warning level instead of debug level. We
/// don't log at warn level every time to avoid flooding the console.
///
/// Every 5 times is arbitrary and can be changed. It's based on running the `lint` goal with a
/// fake store address resulting in 5 read errors and 18 write errors; 5 seems like a
/// reasonable increment.
const LOG_ERRORS_INCREMENT: usize = 5;

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
      read_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
      write_errors_counter: Arc::new(Mutex::new(BTreeMap::new())),
    })
  }

  /// Create a REAPI `Tree` protobuf for an output directory by traversing down from a Pants
  /// merged final output directory to find the specific path to extract. (REAPI requires
  /// output directories to be stored as `Tree` protos that contain all of the `Directory`
  /// protos that constitute the directory tree.)
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
        None => return Ok(None),
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
          None => return Ok(None),
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
          path: String::new(),
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
    with_workunit(
      context.workunit_store.clone(),
      "ensure_action_uploaded".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("ensure action uploaded for {:?}", action_digest)),
        ..WorkunitMetadata::default()
      },
      crate::remote::ensure_action_uploaded(
        &self.store,
        command_digest,
        action_digest,
        request.input_files,
      ),
      |_, md| md,
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

    let update_action_cache_request = remexec::UpdateActionResultRequest {
      instance_name: metadata
        .instance_name
        .as_ref()
        .cloned()
        .unwrap_or_else(|| "".to_owned()),
      action_digest: Some(action_digest.into()),
      action_result: Some(action_result),
      ..remexec::UpdateActionResultRequest::default()
    };

    let mut client = self.action_cache_client.as_ref().clone();
    client
      .update_action_result(update_action_cache_request)
      .await
      .map_err(crate::remote::rpcerror_to_string)?;

    Ok(())
  }
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
    let (command_digest, action_digest) = with_workunit(
      context.workunit_store.clone(),
      "ensure_action_stored_locally".to_owned(),
      WorkunitMetadata {
        level: Level::Trace,
        desc: Some(format!("ensure action stored locally for {:?}", action)),
        ..WorkunitMetadata::default()
      },
      crate::remote::ensure_action_stored_locally(&self.store, &command, &action),
      |_, md| md,
    )
    .await?;

    let mut local_execution_future = self.underlying.run(req, context.clone());

    let result = if self.cache_read {
      // A future to read from the cache and log the results accordingly.
      let cache_read_future = async {
        let response = with_workunit(
          context.workunit_store.clone(),
          "check_action_cache".to_owned(),
          WorkunitMetadata {
            level: Level::Trace,
            desc: Some(format!("check action cache for {:?}", action_digest)),
            ..WorkunitMetadata::default()
          },
          crate::remote::check_action_cache(
            action_digest,
            &self.metadata,
            self.platform,
            &context,
            self.action_cache_client.clone(),
            self.store.clone(),
            self.eager_fetch,
          ),
          |_, md| md,
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
            let err_count = {
              let mut errors_counter = self.read_errors_counter.lock();
              let count = errors_counter.entry(err.clone()).or_insert(0);
              *count += 1;
              *count
            };
            let log_msg = format!(
              "Failed to read from remote cache ({} occurrences so far): {}",
              err_count, err
            );
            if err_count == 1 || err_count % LOG_ERRORS_INCREMENT == 0 {
              log::warn!("{}", log_msg);
            } else {
              log::debug!("{}", log_msg);
            }
            None
          }
        }
      }
      .boxed();

      // We speculate between reading from the remote cache vs. running locally. If there was a
      // cache hit, we return early because there will be no need to write to the cache. Otherwise,
      // we run the process locally and will possibly write it to the cache later.
      tokio::select! {
        cache_result = cache_read_future => {
          if let Some(cached_response) = cache_result {
            let lookup_elapsed = cache_lookup_start.elapsed();
            context.workunit_store.increment_counter(Metric::RemoteCacheSpeculationRemoteCompletedFirst, 1);
            if let Some(time_saved) = cached_response.metadata.time_saved_from_cache(lookup_elapsed) {
              let time_saved = time_saved.as_millis() as u64;
              context
                .workunit_store
                .increment_counter(Metric::RemoteCacheTotalTimeSavedMs, time_saved);
              context
                .workunit_store
                .record_observation(ObservationMetric::RemoteCacheTimeSavedMs, time_saved);
              }
            return Ok(cached_response);
          } else {
            // Note that we don't increment a counter here, as there is nothing of note in this
            // scenario: the remote cache did not save unnecessary local work, nor was the remote
            // trip unusually slow such that local execution was faster.
            local_execution_future.await?
          }
        }
        local_result = &mut local_execution_future => {
          context.workunit_store.increment_counter(Metric::RemoteCacheSpeculationLocalCompletedFirst, 1);
          local_result?
        }
      }
    } else {
      local_execution_future.await?
    };

    if result.exit_code == 0 && self.cache_write {
      let command_runner = self.clone();
      let result = result.clone();
      let context2 = context.clone();
      // NB: We use `TaskExecutor::spawn` instead of `tokio::spawn` to ensure logging still works.
      let cache_write_future = async move {
        context2
          .workunit_store
          .increment_counter(Metric::RemoteCacheWriteStarted, 1);
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
        context2
          .workunit_store
          .increment_counter(Metric::RemoteCacheWriteFinished, 1);
        if let Err(err) = write_result {
          let err_count = {
            let mut errors_counter = command_runner.write_errors_counter.lock();
            let count = errors_counter.entry(err.clone()).or_insert(0);
            *count += 1;
            *count
          };
          let log_msg = format!(
            "Failed to write to remote cache ({} occurrences so far): {}",
            err_count, err
          );
          if err_count == 1 || err_count % LOG_ERRORS_INCREMENT == 0 {
            log::warn!("{}", log_msg);
          } else {
            log::debug!("{}", log_msg);
          }
          context2
            .workunit_store
            .increment_counter(Metric::RemoteCacheWriteErrors, 1);
        };
      }
      .boxed();

      let _write_join = self.executor.spawn(with_workunit(
        context.workunit_store,
        "remote_cache_write".to_owned(),
        WorkunitMetadata {
          level: Level::Trace,
          ..WorkunitMetadata::default()
        },
        cache_write_future,
        |_, md| md,
      ));
    }

    Ok(result)
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    self.underlying.extract_compatible_request(req)
  }
}
