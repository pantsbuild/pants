// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(unused_must_use)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::single_match_else,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(
  clippy::new_without_default,
  clippy::new_without_default_derive,
  clippy::new_ret_no_self
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::collections::HashMap;
use std::path::PathBuf;

use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use futures::future::{self, Future};
use protobuf::{self, Message as GrpcioMessage};

use fs::{File, PathStat};
use hashing::Digest;

use super::{CacheableExecuteProcessRequest, CacheableExecuteProcessResult};

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an ExecuteProcessRequest, and may be populated only by the
// CommandRunner.
const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

/// ???/just a neat way to separate logic as this interface evolves, not really necessary right now
pub trait SerializableProcessExecutionCodec<
    // TODO: add some constraints to these?
    ProcessRequest,
    SerializableRequest,
    ProcessResult,
    SerializableResult,
    ErrorType,
  >: Send + Sync {
  fn convert_request(
    &self,
    req: ProcessRequest
  ) -> Result<SerializableRequest, ErrorType>;

  fn convert_response(
    &self,
    res: ProcessResult,
  ) -> Result<SerializableResult, ErrorType>;

  fn extract_response(
    &self,
    serializable_response: SerializableResult,
  ) -> BoxFuture<ProcessResult, ErrorType>;
}

#[derive(Clone)]
pub struct BazelProtosProcessExecutionCodec {
  store: fs::Store,
}

impl BazelProtosProcessExecutionCodec {
  pub fn new(store: fs::Store) -> Self {
    BazelProtosProcessExecutionCodec { store }
  }

  fn digest_bytes(bytes: &Bytes) -> Digest {
    let fingerprint = fs::Store::fingerprint_from_bytes_unsafe(&bytes);
    Digest(fingerprint, bytes.len())
  }

  pub fn digest_message(message: &dyn GrpcioMessage) -> Result<Digest, String> {
    let bytes = message.write_to_bytes().map_err(|e| format!("{:?}", e))?;
    Ok(Self::digest_bytes(&Bytes::from(bytes.as_slice())))
  }

  fn convert_digest(digest: Digest) -> bazel_protos::remote_execution::Digest {
    let mut digest_proto = bazel_protos::remote_execution::Digest::new();
    let Digest(fingerprint, bytes_len) = digest;
    digest_proto.set_hash(fingerprint.to_hex());
    digest_proto.set_size_bytes(bytes_len as i64);
    digest_proto
  }

  fn make_command(
    req: CacheableExecuteProcessRequest,
  ) -> Result<bazel_protos::remote_execution::Command, String> {
    let CacheableExecuteProcessRequest {
      req,
      cache_key_gen_version,
    } = req;
    let mut command = bazel_protos::remote_execution::Command::new();
    command.set_arguments(protobuf::RepeatedField::from_vec(req.argv.clone()));

    for (ref name, ref value) in &req.env {
      if name.as_str() == CACHE_KEY_GEN_VERSION_ENV_VAR_NAME {
        return Err(format!(
          "Cannot set env var with name {} as that is reserved for internal use by pants",
          CACHE_KEY_GEN_VERSION_ENV_VAR_NAME
        ));
      }
      let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
      env.set_name(name.to_string());
      env.set_value(value.to_string());
      command.mut_environment_variables().push(env);
    }
    if let Some(cache_key_gen_version) = cache_key_gen_version {
      let mut env = bazel_protos::remote_execution::Command_EnvironmentVariable::new();
      env.set_name(CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_string());
      env.set_value(cache_key_gen_version.to_string());
      command.mut_environment_variables().push(env);
    }
    let mut output_files = req
      .output_files
      .iter()
      .map(|p| {
        p.to_str()
          .map(|s| s.to_owned())
          .ok_or_else(|| format!("Non-UTF8 output file path: {:?}", p))
      })
      .collect::<Result<Vec<String>, String>>()?;
    output_files.sort();
    command.set_output_files(protobuf::RepeatedField::from_vec(output_files));

    let mut output_directories = req
      .output_directories
      .iter()
      .map(|p| {
        p.to_str()
          .map(|s| s.to_owned())
          .ok_or_else(|| format!("Non-UTF8 output directory path: {:?}", p))
      })
      .collect::<Result<Vec<String>, String>>()?;
    output_directories.sort();
    command.set_output_directories(protobuf::RepeatedField::from_vec(output_directories));

    // Ideally, the JDK would be brought along as part of the input directory, but we don't currently
    // have support for that. The platform with which we're experimenting for remote execution
    // supports this property, and will symlink .jdk to a system-installed JDK:
    // https://github.com/twitter/scoot/pull/391
    if req.jdk_home.is_some() {
      command.set_platform({
        let mut platform = bazel_protos::remote_execution::Platform::new();
        platform.mut_properties().push({
          let mut property = bazel_protos::remote_execution::Platform_Property::new();
          property.set_name("JDK_SYMLINK".to_owned());
          property.set_value(".jdk".to_owned());
          property
        });
        platform
      });
    }

    Ok(command)
  }

  pub fn make_action_with_command(
    req: CacheableExecuteProcessRequest,
  ) -> Result<
    (
      bazel_protos::remote_execution::Action,
      bazel_protos::remote_execution::Command,
    ),
    String,
  > {
    let command = Self::make_command(req.clone())?;
    let mut action = bazel_protos::remote_execution::Action::new();
    action.set_command_digest((&Self::digest_message(&command)?).into());
    action.set_input_root_digest((&req.req.input_files).into());
    Ok((action, command))
  }

  fn extract_stdout(
    &self,
    result: bazel_protos::remote_execution::ActionResult,
  ) -> BoxFuture<Bytes, String> {
    if let Some(ref stdout_digest) = result.stdout_digest.into_option() {
      let stdout_digest_result: Result<Digest, String> = stdout_digest.into();
      let stdout_digest = try_future!(
        stdout_digest_result.map_err(|err| format!("Error extracting stdout: {}", err))
      );
      self
        .store
        .load_file_bytes_with(stdout_digest, |v| v)
        .map_err(move |error| {
          format!(
            "Error fetching stdout digest ({:?}): {:?}",
            stdout_digest, error
          )
        })
        .and_then(move |maybe_value| {
          maybe_value.ok_or_else(|| {
            format!(
              "Couldn't find stdout digest ({:?}), when fetching.",
              stdout_digest
            )
          })
        })
        .to_boxed()
    } else {
      let stdout_raw = result.stdout_raw;
      let stdout_copy = stdout_raw.clone();
      self
        .store
        .store_file_bytes(stdout_raw, true)
        .map_err(move |error| format!("Error storing raw stdout: {:?}", error))
        .map(|_| stdout_copy)
        .to_boxed()
    }
  }

  fn extract_stderr(
    &self,
    result: bazel_protos::remote_execution::ActionResult,
  ) -> BoxFuture<Bytes, String> {
    if let Some(ref stderr_digest) = result.stderr_digest.into_option() {
      let stderr_digest_result: Result<Digest, String> = stderr_digest.into();
      let stderr_digest = try_future!(
        stderr_digest_result.map_err(|err| format!("Error extracting stderr: {}", err))
      );
      self
        .store
        .load_file_bytes_with(stderr_digest, |v| v)
        .map_err(move |error| {
          format!(
            "Error fetching stderr digest ({:?}): {:?}",
            stderr_digest, error
          )
        })
        .and_then(move |maybe_value| {
          maybe_value.ok_or_else(|| {
            format!(
              "Couldn't find stderr digest ({:?}), when fetching.",
              stderr_digest
            )
          })
        })
        .to_boxed()
    } else {
      let stderr_raw = result.stderr_raw;
      let stderr_copy = stderr_raw.clone();
      self
        .store
        .store_file_bytes(stderr_raw, true)
        .map_err(move |error| format!("Error storing raw stderr: {:?}", error))
        .map(|_| stderr_copy)
        .to_boxed()
    }
  }

  fn extract_output_files(
    &self,
    result: bazel_protos::remote_execution::ActionResult,
  ) -> BoxFuture<Digest, String> {
    // Get Digests of output Directories.
    // Then we'll make a Directory for the output files, and merge them.
    let output_directories = result.output_directories.clone();
    let mut directory_digests = Vec::with_capacity(output_directories.len() + 1);
    for dir in output_directories.into_iter() {
      let digest_result: Result<Digest, String> = (&dir.tree_digest.unwrap()).into();
      let mut digest = future::done(digest_result).to_boxed();
      for component in dir.path.rsplit('/') {
        let component = component.to_owned();
        let store = self.store.clone();
        digest = digest
          .and_then(move |digest| {
            let mut directory = bazel_protos::remote_execution::Directory::new();
            directory.mut_directories().push({
              let mut node = bazel_protos::remote_execution::DirectoryNode::new();
              node.set_name(component);
              node.set_digest((&digest).into());
              node
            });
            store.record_directory(&directory, true)
          })
          .to_boxed();
      }
      directory_digests
        .push(digest.map_err(|err| format!("Error saving remote output directory: {}", err)));
    }

    // Make a directory for the files
    let mut path_map = HashMap::new();
    let output_files = result.output_files.clone();
    let path_stats_result: Result<Vec<PathStat>, String> = output_files
      .into_iter()
      .map(|output_file| {
        let output_file_path_buf = PathBuf::from(output_file.path);
        let digest = output_file
          .digest
          .into_option()
          .ok_or_else(|| "No digest on remote execution output file".to_string())?;
        let digest: Result<Digest, String> = (&digest).into();
        path_map.insert(output_file_path_buf.clone(), digest?);
        Ok(PathStat::file(
          output_file_path_buf.clone(),
          File {
            path: output_file_path_buf,
            is_executable: output_file.is_executable,
          },
        ))
      })
      .collect();

    let path_stats = try_future!(path_stats_result);

    #[derive(Clone)]
    struct StoreOneOffRemoteDigest {
      map_of_paths_to_digests: HashMap<PathBuf, Digest>,
    }

    impl StoreOneOffRemoteDigest {
      fn new(map: HashMap<PathBuf, Digest>) -> StoreOneOffRemoteDigest {
        StoreOneOffRemoteDigest {
          map_of_paths_to_digests: map,
        }
      }
    }

    impl fs::StoreFileByDigest<String> for StoreOneOffRemoteDigest {
      fn store_by_digest(&self, file: File) -> BoxFuture<Digest, String> {
        match self.map_of_paths_to_digests.get(&file.path) {
          Some(digest) => future::ok(*digest),
          None => future::err(format!(
            "Didn't know digest for path in remote execution response: {:?}",
            file.path
          )),
        }
        .to_boxed()
      }
    }

    let store = self.store.clone();
    fs::Snapshot::digest_from_path_stats(
      self.store.clone(),
      &StoreOneOffRemoteDigest::new(path_map),
      &path_stats,
    )
    .map_err(move |error| {
      format!(
        "Error when storing the output file directory info in the remote CAS: {:?}",
        error
      )
    })
    .join(future::join_all(directory_digests))
    .and_then(|(files_digest, mut directory_digests)| {
      directory_digests.push(files_digest);
      fs::Snapshot::merge_directories(store, directory_digests)
        .map_err(|err| format!("Error when merging output files and directories: {}", err))
    })
    .to_boxed()
  }
}

impl
  SerializableProcessExecutionCodec<
    CacheableExecuteProcessRequest,
    bazel_protos::remote_execution::Action,
    CacheableExecuteProcessResult,
    bazel_protos::remote_execution::ActionResult,
    // TODO: better error type?
    String,
  > for BazelProtosProcessExecutionCodec
{
  fn convert_request(
    &self,
    req: CacheableExecuteProcessRequest,
  ) -> Result<bazel_protos::remote_execution::Action, String> {
    let (action, _) = Self::make_action_with_command(req)?;
    Ok(action)
  }

  fn convert_response(
    &self,
    res: CacheableExecuteProcessResult,
  ) -> Result<bazel_protos::remote_execution::ActionResult, String> {
    let mut action_proto = bazel_protos::remote_execution::ActionResult::new();
    let mut output_directory = bazel_protos::remote_execution::OutputDirectory::new();
    let output_directory_digest = Self::convert_digest(res.output_directory);
    output_directory.set_tree_digest(output_directory_digest);
    action_proto.set_output_directories(protobuf::RepeatedField::from_vec(vec![output_directory]));
    action_proto.set_exit_code(res.exit_code);
    action_proto.set_stdout_raw(res.stdout.clone());
    action_proto.set_stdout_digest(Self::convert_digest(Self::digest_bytes(&res.stdout)));
    action_proto.set_stderr_raw(res.stderr.clone());
    action_proto.set_stderr_digest(Self::convert_digest(Self::digest_bytes(&res.stderr)));
    Ok(action_proto)
  }

  fn extract_response(
    &self,
    res: bazel_protos::remote_execution::ActionResult,
  ) -> BoxFuture<CacheableExecuteProcessResult, String> {
    self
      .extract_stdout(res.clone())
      .join(self.extract_stderr(res.clone()))
      .join(self.extract_output_files(res.clone()))
      .map(
        move |((stdout, stderr), output_directory)| CacheableExecuteProcessResult {
          stdout,
          stderr,
          exit_code: res.exit_code,
          output_directory,
        },
      )
      .to_boxed()
  }
}

/// ???/it's called "immediate" because it's a best-effort thing located locally (???)
pub trait ImmediateExecutionCache<ProcessRequest, ProcessResult>: Send + Sync {
  fn record_process_result(&self, req: ProcessRequest, res: ProcessResult)
    -> BoxFuture<(), String>;

  fn load_process_result(&self, req: ProcessRequest) -> BoxFuture<Option<ProcessResult>, String>;
}

/// ???
#[derive(Clone)]
pub struct ActionCache {
  store: fs::Store,
  process_execution_codec: BazelProtosProcessExecutionCodec,
}

impl ActionCache {
  pub fn new(store: fs::Store) -> Self {
    ActionCache {
      store: store.clone(),
      process_execution_codec: BazelProtosProcessExecutionCodec::new(store),
    }
  }
}

impl ImmediateExecutionCache<CacheableExecuteProcessRequest, CacheableExecuteProcessResult>
  for ActionCache
{
  fn record_process_result(
    &self,
    req: CacheableExecuteProcessRequest,
    res: CacheableExecuteProcessResult,
  ) -> BoxFuture<(), String> {
    let codec = self.process_execution_codec.clone();
    let converted_key_value_protos = codec
      .convert_request(req)
      .and_then(|req| codec.convert_response(res).map(|res| (req, res)));
    let store = self.store.clone();
    future::result(converted_key_value_protos)
      .and_then(move |(action_request, action_result)| {
        store.record_process_result(action_request, action_result)
      })
      .to_boxed()
  }

  fn load_process_result(
    &self,
    req: CacheableExecuteProcessRequest,
  ) -> BoxFuture<Option<CacheableExecuteProcessResult>, String> {
    let codec = self.process_execution_codec.clone();
    let store = self.store.clone();
    future::result(codec.convert_request(req))
      .and_then(move |action_proto| store.load_process_result(action_proto))
      .and_then(move |maybe_action_result| match maybe_action_result {
        Some(action_result) => codec.extract_response(action_result).map(Some).to_boxed(),
        None => future::result(Ok(None)).to_boxed(),
      })
      .to_boxed()
  }
}
