use crate::{
  Context, ExecuteProcessRequest, ExecuteProcessRequestMetadata, FallibleExecuteProcessResult,
  MultiPlatformExecuteProcessRequest,
};
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use digest::{Digest as DigestTrait, FixedOutput};
use futures::Future;
use hashing::{Digest, Fingerprint};
use log::{debug, warn};
use protobuf::Message;
use sha2::Sha256;
use sharded_lmdb::ShardedLmdb;
use std::sync::Arc;
use store::Store;

#[derive(Clone)]
pub struct CommandRunner {
  pub underlying: Arc<dyn crate::CommandRunner>,
  pub process_execution_store: ShardedLmdb,
  pub file_store: Store,
  pub metadata: ExecuteProcessRequestMetadata,
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
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let digest = self.digest(req.clone());
    let key = digest.0;

    let command_runner = self.clone();
    self
      .lookup(key, context.clone())
      .then(move |maybe_result| {
        match maybe_result {
          Ok(Some(result)) => return futures::future::ok(result).to_boxed(),
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
              futures::future::ok(result).to_boxed()
            }
          })
          .to_boxed()

      })
      .to_boxed()
  }
}

impl CommandRunner {
  fn bytes_to_digest(&self, bytes: &[u8]) -> Digest {
    let mut hasher = Sha256::default();
    hasher.input(bytes);

    Digest(
      Fingerprint::from_bytes_unsafe(&hasher.fixed_result()),
      bytes.len(),
    )
  }

  fn digest(&self, req: MultiPlatformExecuteProcessRequest) -> Digest {
    let mut hashes: Vec<String> = req
      .0
      .values()
      .map(|ref epr| crate::remote::make_execute_request(epr, self.metadata.clone()).unwrap())
      .map(|(_a, _b, er)| er.get_action_digest().get_hash().to_string())
      .collect();
    hashes.sort();
    self.bytes_to_digest(
      hashes
        .iter()
        .fold(String::new(), |mut acc, hash| {
          acc.push_str(&hash);
          acc
        })
        .as_bytes(),
    )
  }

  fn lookup(
    &self,
    fingerprint: Fingerprint,
    context: Context,
  ) -> impl Future<Item = Option<FallibleExecuteProcessResult>, Error = String> {
    let file_store = self.file_store.clone();
    self
      .process_execution_store
      .load_bytes_with(fingerprint, |bytes| {
        let mut execute_response = bazel_protos::remote_execution::ExecuteResponse::new();
        execute_response
          .merge_from_bytes(&bytes)
          .map_err(|e| format!("Invalid ExecuteResponse: {:?}", e))?;
        Ok(execute_response)
      })
      .and_then(move |maybe_execute_response| {
        if let Some(execute_response) = maybe_execute_response {
          crate::remote::populate_fallible_execution_result(
            file_store,
            execute_response,
            vec![],
            context.workunit_store,
          )
          .map(Some)
          .to_boxed()
        } else {
          futures::future::ok(None).to_boxed()
        }
      })
  }

  fn store(
    &self,
    fingerprint: Fingerprint,
    result: &FallibleExecuteProcessResult,
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
          .map(Bytes::from)
          .map_err(|err| format!("Error serializing execute process result to cache: {}", err))
      })
      .and_then(move |bytes| process_execution_store.store_bytes(fingerprint, bytes, false))
  }
}
