use crate::{
  ExecuteProcessRequest, ExecuteProcessRequestMetadata, FallibleExecuteProcessResult,
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
use workunit_store::WorkUnitStore;

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
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let digest = self.digest(req.clone());
    let key = digest.0;

    let command_runner = self.clone();
    self
      .lookup(key, workunit_store.clone())
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
            .run(req, workunit_store)
            .and_then(move |result| {
              command_runner.store(key, &result).then(|store_result| {
                if let Err(err) = store_result {
                  debug!("Error storing process execution result to local cache: {} - ignoring and continuing", err);
                }
                Ok(result)
              })
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
    workunit_store: WorkUnitStore,
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
            workunit_store,
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

#[cfg(test)]
mod test {
  use crate::{CommandRunner as CommandRunnerTrait, ExecuteProcessRequestMetadata};
  use crate::{ExecuteProcessRequest, Platform};
  use hashing::EMPTY_DIGEST;
  use sharded_lmdb::ShardedLmdb;
  use std::collections::{BTreeMap, BTreeSet};
  use std::io::Write;
  use std::path::PathBuf;
  use std::sync::Arc;
  use std::time::Duration;
  use store::Store;
  use tempfile::TempDir;
  use testutil::data::TestData;
  use workunit_store::WorkUnitStore;

  #[test]
  fn roundtrip() {
    let runtime = task_executor::Executor::new();
    let work_dir = TempDir::new().unwrap();
    let store_dir = TempDir::new().unwrap();
    let store = Store::local_only(runtime.clone(), store_dir.path()).unwrap();
    let local = crate::local::CommandRunner::new(
      store.clone(),
      runtime.clone(),
      work_dir.path().to_owned(),
      true,
    );

    let script_dir = TempDir::new().unwrap();
    let script_path = script_dir.path().join("script");
    std::fs::File::create(&script_path)
      .and_then(|mut file| {
        writeln!(
          file,
          "echo -n {} > roland && echo Hello && echo >&2 World",
          TestData::roland().string(),
        )
      })
      .unwrap();

    let request = ExecuteProcessRequest {
      argv: vec![
        testutil::path::find_bash(),
        format!("{}", script_path.display()),
      ],
      env: BTreeMap::new(),
      input_files: EMPTY_DIGEST,
      output_files: vec![PathBuf::from("roland")].into_iter().collect(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "bash".to_string(),
      unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
        hashing::EMPTY_DIGEST,
      jdk_home: None,
      target_platform: Platform::None,
    };

    let local_result = runtime.block_on(local.run(request.clone().into(), WorkUnitStore::new()));

    let cache_dir = TempDir::new().unwrap();
    let caching = crate::cache::CommandRunner {
      underlying: Arc::new(local),
      file_store: store.clone(),
      process_execution_store: ShardedLmdb::new(
        cache_dir.path().to_owned(),
        50 * 1024 * 1024,
        runtime.clone(),
      )
      .unwrap(),
      metadata: ExecuteProcessRequestMetadata {
        instance_name: None,
        cache_key_gen_version: None,
        platform_properties: BTreeMap::new(),
      },
    };

    let uncached_result =
      runtime.block_on(caching.run(request.clone().into(), WorkUnitStore::new()));

    assert_eq!(local_result, uncached_result);

    std::fs::remove_file(&script_path).unwrap();
    let cached_result = runtime.block_on(caching.run(request.into(), WorkUnitStore::new()));

    assert_eq!(uncached_result, cached_result);
  }
}
