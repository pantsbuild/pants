use crate::{
  Context, FallibleProcessResultWithPlatform, MultiPlatformProcess, Platform, Process,
  ProcessMetadata,
};
use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use futures::compat::Future01CompatExt;
use futures::{future as future03, FutureExt};
use log::{debug, warn};
use protobuf::Message;
use serde::{Deserialize, Serialize};

use hashing::Fingerprint;
use sharded_lmdb::ShardedLmdb;
use store::Store;

#[allow(dead_code)]
#[derive(Serialize, Deserialize)]
struct PlatformAndResponseBytes {
  platform: Platform,
  response_bytes: Vec<u8>,
}

#[derive(Clone)]
pub struct CommandRunner {
  underlying: Arc<dyn crate::CommandRunner>,
  process_execution_store: ShardedLmdb,
  file_store: Store,
  metadata: ProcessMetadata,
}

impl CommandRunner {
  pub fn new(
    underlying: Arc<dyn crate::CommandRunner>,
    process_execution_store: ShardedLmdb,
    file_store: Store,
    metadata: ProcessMetadata,
  ) -> CommandRunner {
    CommandRunner {
      underlying,
      process_execution_store,
      file_store,
      metadata,
    }
  }
}

#[async_trait]
impl crate::CommandRunner for CommandRunner {
  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    self.underlying.extract_compatible_request(req)
  }

  // TODO: Maybe record WorkUnits for local cache checks.
  async fn run(
    &self,
    req: MultiPlatformProcess,
    context: Context,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let digest = crate::digest(req.clone(), &self.metadata);
    let key = digest.0;

    let command_runner = self.clone();
    match self.lookup(key).await {
      Ok(Some(result)) => return Ok(result),
      Err(err) => {
        debug!(
          "Error loading process execution result from local cache: {} - continuing to execute",
          err
        );
        // Falling through to re-execute.
      }
      Ok(None) => {
        // Falling through to execute.
      }
    }

    let result = command_runner.underlying.run(req, context).await?;
    if result.exit_code == 0 {
      if let Err(err) = command_runner.store(key, &result).await {
        warn!(
          "Error storing process execution result to local cache: {} - ignoring and continuing",
          err
        );
      }
    }
    Ok(result)
  }
}

impl CommandRunner {
  async fn lookup(
    &self,
    fingerprint: Fingerprint,
  ) -> Result<Option<FallibleProcessResultWithPlatform>, String> {
    use bazel_protos::remote_execution::ExecuteResponse;

    // See whether there is a cache entry.
    let maybe_execute_response: Option<(ExecuteResponse, Platform)> = self
      .process_execution_store
      .load_bytes_with(fingerprint, move |bytes| {
        let decoded: PlatformAndResponseBytes = bincode::deserialize(&bytes[..])
          .map_err(|err| format!("Could not deserialize platform and response: {}", err))?;

        let platform = decoded.platform;

        let mut execute_response = ExecuteResponse::new();
        execute_response
          .merge_from_bytes(&decoded.response_bytes)
          .map_err(|e| format!("Invalid ExecuteResponse: {:?}", e))?;

        Ok((execute_response, platform))
      })
      .await?;

    // Deserialize the cache entry if it existed.
    let result = if let Some((execute_response, platform)) = maybe_execute_response {
      crate::remote::populate_fallible_execution_result(
        self.file_store.clone(),
        execute_response,
        vec![],
        platform,
      )
      .compat()
      .await?
    } else {
      return Ok(None);
    };

    // Ensure that all digests in the result are loadable, erroring if any are not.
    let _ = future03::try_join_all(vec![
      self
        .file_store
        .ensure_local_has_file(result.stdout_digest)
        .boxed(),
      self
        .file_store
        .ensure_local_has_file(result.stderr_digest)
        .boxed(),
      self
        .file_store
        .ensure_local_has_recursive_directory(result.output_directory)
        .compat()
        .boxed(),
    ])
    .await?;

    Ok(Some(result))
  }

  async fn store(
    &self,
    fingerprint: Fingerprint,
    result: &FallibleProcessResultWithPlatform,
  ) -> Result<(), String> {
    let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
    execute_response.set_cached_result(true);
    let action_result = execute_response.mut_result();
    action_result.set_exit_code(result.exit_code);
    action_result.mut_output_directories().push({
      let mut directory = bazel_protos::remote_execution::OutputDirectory::new();
      directory.set_path(String::new());
      directory.set_tree_digest((&result.output_directory).into());
      directory
    });
    // TODO: Should probably have a configurable lease time which is larger than default.
    // (This isn't super urgent because we don't ever actually GC this store. So also...)
    // TODO: GC the local process execution cache.

    let stdout_digest = result.stdout_digest;
    let stderr_digest = result.stderr_digest;

    let action_result = execute_response.mut_result();
    action_result.set_stdout_digest((&stdout_digest).into());
    action_result.set_stderr_digest((&stderr_digest).into());
    let response_bytes = execute_response
      .write_to_bytes()
      .map_err(|err| format!("Error serializing execute process result to cache: {}", err))?;

    let bytes_to_store = bincode::serialize(&PlatformAndResponseBytes {
      platform: result.platform,
      response_bytes,
    })
    .map(Bytes::from)
    .map_err(|err| {
      format!(
        "Error serializing platform and execute process result: {}",
        err
      )
    })?;

    self
      .process_execution_store
      .store_bytes(fingerprint, bytes_to_store, false)
      .await
  }
}
