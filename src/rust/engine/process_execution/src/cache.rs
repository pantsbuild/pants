use crate::{
  Context, ExecuteProcessRequest, ExecuteProcessRequestMetadata,
  FallibleExecuteProcessResultWithPlatform, MultiPlatformExecuteProcessRequest, Platform,
};
use std::sync::Arc;

use bincode;
use bytes::Bytes;
use futures01::{future, Future};
use log::{debug, warn};
use protobuf::Message;

use boxfuture::{BoxFuture, Boxable};
use hashing::Fingerprint;
use serde::{Deserialize, Serialize};
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
  metadata: ExecuteProcessRequestMetadata,
}

impl CommandRunner {
  pub fn new(
    underlying: Arc<dyn crate::CommandRunner>,
    process_execution_store: ShardedLmdb,
    file_store: Store,
    metadata: ExecuteProcessRequestMetadata,
  ) -> CommandRunner {
    CommandRunner {
      underlying,
      process_execution_store,
      file_store,
      metadata,
    }
  }
}

impl crate::CommandRunner for CommandRunner {
  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    self.underlying.extract_compatible_request(req)
  }

  // TODO: Maybe record WorkUnits for local cache checks.
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResultWithPlatform, String> {
    let digest = crate::digest(req.clone(), &self.metadata);
    let key = digest.0;

    let command_runner = self.clone();
    self
      .lookup(key, context.clone())
      .then(move |maybe_result| {
        match maybe_result {
          Ok(Some(result)) => return future::ok(result).to_boxed(),
          Err(err) => {
            warn!("Error loading process execution result from local cache: {} - continuing to execute", err);
            // Falling through to re-execute.
          },
          Ok(None) => {
            // Falling through to execute.
          },
        }
        command_runner
          .underlying
          .run(req, context)
          .and_then(move |result| {
            if result.exit_code == 0 {
              command_runner
                .store(key, &result)
                .then(|store_result| {
                  if let Err(err) = store_result {
                    debug!("Error storing process execution result to local cache: {} - ignoring and continuing", err);
                  }
                  Ok(result)
                }).to_boxed()
            } else {
              future::ok(result).to_boxed()
            }
          })
          .to_boxed()

      })
      .to_boxed()
  }
}

impl CommandRunner {
  fn lookup(
    &self,
    fingerprint: Fingerprint,
    context: Context,
  ) -> impl Future<Item = Option<FallibleExecuteProcessResultWithPlatform>, Error = String> {
    use bazel_protos::remote_execution::ExecuteResponse;
    let file_store = self.file_store.clone();

    self
      .process_execution_store
      .load_bytes_with(fingerprint.clone(), move |bytes| {
        let decoded: PlatformAndResponseBytes = bincode::deserialize(&bytes[..])
          .map_err(|err| format!("Could not deserialize platform and response: {}", err))?;

        let platform = decoded.platform;

        let mut execute_response = ExecuteResponse::new();
        execute_response
          .merge_from_bytes(&decoded.response_bytes)
          .map_err(|e| format!("Invalid ExecuteResponse: {:?}", e))?;

        Ok((execute_response, platform))
      })
      .and_then(
        move |maybe_execute_response: Option<(ExecuteResponse, Platform)>| {
          if let Some((execute_response, platform)) = maybe_execute_response {
            crate::remote::populate_fallible_execution_result(
              file_store,
              execute_response,
              vec![],
              context.workunit_store,
              platform,
            )
            .map(Some)
            .to_boxed()
          } else {
            future::ok(None).to_boxed()
          }
        },
      )
  }

  fn store(
    &self,
    fingerprint: Fingerprint,
    result: &FallibleExecuteProcessResultWithPlatform,
  ) -> impl Future<Item = (), Error = String> {
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
    let process_execution_store = self.process_execution_store.clone();
    // TODO: Should probably have a configurable lease time which is larger than default.
    // (This isn't super urgent because we don't ever actually GC this store. So also...)
    // TODO: GC the local process execution cache.
    //

    let platform = result.platform;

    self
      .file_store
      .store_file_bytes(result.stdout.clone(), true)
      .join(
        self
          .file_store
          .store_file_bytes(result.stderr.clone(), true),
      )
      .and_then(move |(stdout_digest, stderr_digest)| {
        let action_result = execute_response.mut_result();
        action_result.set_stdout_digest((&stdout_digest).into());
        action_result.set_stderr_digest((&stderr_digest).into());
        execute_response
          .write_to_bytes()
          .map_err(|err| format!("Error serializing execute process result to cache: {}", err))
      })
      .and_then(move |response_bytes: Vec<u8>| {
        let bytes_to_store = bincode::serialize(&PlatformAndResponseBytes {
          platform,
          response_bytes,
        })
        .map(Bytes::from)
        .map_err(|err| {
          format!(
            "Error serializing platform and execute process result: {}",
            err
          )
        });
        future::result(bytes_to_store)
      })
      .and_then(move |bytes: Bytes| process_execution_store.store_bytes(fingerprint, bytes, false))
  }
}
