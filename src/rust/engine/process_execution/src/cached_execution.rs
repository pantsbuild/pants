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
use std::sync::Arc;

use boxfuture::{try_future, BoxFuture, Boxable};
use bytes::Bytes;
use futures::future::{self, Future};
use log::debug;
use protobuf::{self, Message as GrpcioMessage};

use fs::{File, PathStat};
use hashing::Digest;

use super::{CommandRunner, ExecuteProcessRequest, ExecutionStats, FallibleExecuteProcessResult};

// Environment variable which is exclusively used for cache key invalidation.
// This may be not specified in an ExecuteProcessRequest, and may be populated only by the
// CommandRunner.
pub const CACHE_KEY_GEN_VERSION_ENV_VAR_NAME: &str = "PANTS_CACHE_KEY_GEN_VERSION";

/// ???/DON'T LET THE `cache_key_gen_version` BECOME A KITCHEN SINK!!!
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CacheableExecuteProcessRequest {
  req: ExecuteProcessRequest,
  // TODO: give this a better type than Option<String> (everywhere)!
  cache_key_gen_version: Option<String>,
}

impl CacheableExecuteProcessRequest {
  pub fn new(req: ExecuteProcessRequest, cache_key_gen_version: Option<String>) -> Self {
    CacheableExecuteProcessRequest {
      req,
      cache_key_gen_version,
    }
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CacheableExecuteProcessResult {
  pub stdout: Bytes,
  pub stderr: Bytes,
  pub exit_code: i32,
  pub output_directory: hashing::Digest,
}

impl CacheableExecuteProcessResult {
  pub fn with_execution_attempts(
    &self,
    execution_attempts: Vec<ExecutionStats>,
  ) -> FallibleExecuteProcessResult {
    FallibleExecuteProcessResult {
      stdout: self.stdout.clone(),
      stderr: self.stderr.clone(),
      exit_code: self.exit_code,
      output_directory: self.output_directory,
      execution_attempts,
    }
  }
}

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
  // NB: This could be an Arc<Box<dyn SerializableProcessExecutionCodec<...>>> if we ever need to
  // add any further such codecs. This type is static in this struct, because the codec is required
  // to produce specifically Action and ActionResult, because that is what is currently accepted by
  // `store.record_process_result()`.
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
      .and_then(|req| codec.convert_response(res.clone()).map(|res| (req, res)));
    let store = self.store.clone();
    future::result(converted_key_value_protos)
      .and_then(move |(action_request, action_result)| {
        store
          .store_file_bytes(res.stdout, true)
          .join(store.store_file_bytes(res.stderr, true))
          .and_then(move |(_, _)| {
            // NB: We wait until the stdout and stderr digests have been successfully recorded, so
            // that we don't later attempt to read digests in the `action_result` which don't exist.
            store.record_process_result(action_request, action_result)
          })
          .to_boxed()
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

///
/// A CommandRunner wrapper that attempts to cache process executions.
///
#[derive(Clone)]
pub struct CachingCommandRunner {
  inner: Arc<Box<dyn CommandRunner>>,
  cache: Arc<
    Box<dyn ImmediateExecutionCache<CacheableExecuteProcessRequest, CacheableExecuteProcessResult>>,
  >,
  cache_key_gen_version: Option<String>,
}

impl CachingCommandRunner {
  pub fn from_store(
    inner: Box<dyn CommandRunner>,
    store: fs::Store,
    cache_key_gen_version: Option<String>,
  ) -> Self {
    let action_cache = ActionCache::new(store);
    let boxed_cache = Box::new(action_cache)
      as Box<
        dyn ImmediateExecutionCache<CacheableExecuteProcessRequest, CacheableExecuteProcessResult>,
      >;
    Self::new(inner, boxed_cache, cache_key_gen_version)
  }

  pub fn new(
    inner: Box<dyn CommandRunner>,
    cache: Box<
      dyn ImmediateExecutionCache<CacheableExecuteProcessRequest, CacheableExecuteProcessResult>,
    >,
    cache_key_gen_version: Option<String>,
  ) -> Self {
    CachingCommandRunner {
      inner: Arc::new(inner),
      cache: Arc::new(cache),
      cache_key_gen_version,
    }
  }
}

impl CommandRunner for CachingCommandRunner {
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let cacheable_request =
      CacheableExecuteProcessRequest::new(req.clone(), self.cache_key_gen_version.clone());
    let cache = self.cache.clone();
    let inner = self.inner.clone();
    cache
      .load_process_result(cacheable_request.clone())
      .and_then(move |cache_fetch| match cache_fetch {
        // We have a cache hit!
        Some(cached_execution_result) => {
          debug!(
            "cached execution for request {:?}! {:?}",
            req.clone(),
            cached_execution_result
          );
          future::result(Ok(cached_execution_result)).to_boxed()
        }
        // We have to actually run the process now.
        None => inner
          .run(req.clone())
          .and_then(move |res| {
            debug!("uncached execution for request {:?}: {:?}", req, res);
            let cacheable_process_result = res.into_cacheable();
            cache
              .record_process_result(cacheable_request.clone(), cacheable_process_result.clone())
              .map(move |()| {
                debug!(
                  "request {:?} should now be cached as {:?}",
                  cacheable_request.clone(),
                  cacheable_process_result.clone()
                );
                cacheable_process_result
              })
          })
          .to_boxed(),
      })
      // NB: We clear metadata about execution attempts when returning a cacheable process execution
      // result.
      .map(|cacheable_process_result| cacheable_process_result.with_execution_attempts(vec![]))
      .to_boxed()
  }
}

#[cfg(test)]
mod tests {
  use super::{
    ActionCache, CacheableExecuteProcessRequest, CacheableExecuteProcessResult,
    CachingCommandRunner, CommandRunner, ExecuteProcessRequest, ImmediateExecutionCache,
  };
  use futures::future::Future;
  use std::collections::{BTreeMap, BTreeSet};
  use std::ops::Deref;
  use std::path::Path;
  use std::sync::Arc;
  use std::time::Duration;
  use tempfile::TempDir;
  use testutil::owned_string_vec;

  // // TODO: test codec back and forth
  // #[test]
  // fn bazel_proto_process_execution_codec() {
  //   let req = ExecuteProcessRequest {
  //     argv: owned_string_vec(&["ls", "-R", "/"]),
  //     env: BTreeMap::new(),
  //     input_files: fs::EMPTY_DIGEST,
  //     output_files:
  //   }
  // }

  #[test]
  #[cfg(unix)]
  fn cached_process_execution() {
    let random_perl = output_only_process_request(owned_string_vec(&[
      "/usr/bin/perl",
      "-e",
      "print(rand(10))",
    ]));
    let store_dir = TempDir::new().unwrap();
    let work_dir = TempDir::new().unwrap();
    let (_, base_runner, action_cache) = cache_in_dir(store_dir.path(), work_dir.path());
    let cacheable_perl = CacheableExecuteProcessRequest {
      req: random_perl.clone(),
      cache_key_gen_version: None,
    };
    assert_eq!(
      Ok(None),
      action_cache
        .load_process_result(cacheable_perl.clone())
        .wait()
    );
    let caching_runner = make_caching_runner(base_runner.clone(), action_cache.clone(), None);
    let process_result = caching_runner.run(random_perl.clone()).wait().unwrap();
    assert_eq!(0, process_result.exit_code);
    // A "cacheable" process execution result won't have e.g. the number of attempts that the
    // process was tried, for idempotency, but everything else should be the same.
    assert_eq!(
      process_result.clone().into_cacheable(),
      action_cache
        .load_process_result(cacheable_perl)
        .wait()
        .unwrap()
        .unwrap()
    );
    let perl_number = String::from_utf8(process_result.stdout.deref().to_vec())
      .unwrap()
      .parse::<f64>()
      .unwrap();
    // Try again and verify the result is cached (the random number is still the same).
    let second_process_result = caching_runner.run(random_perl.clone()).wait().unwrap();
    let second_perl_number = String::from_utf8(second_process_result.stdout.deref().to_vec())
      .unwrap()
      .parse::<f64>()
      .unwrap();
    assert_eq!(perl_number, second_perl_number);
    // See that the result is invalidated if a `cache_key_gen_version` is provided.
    let new_key = "xx".to_string();
    let new_cacheable_perl = CacheableExecuteProcessRequest {
      req: random_perl.clone(),
      cache_key_gen_version: Some(new_key.clone()),
    };
    assert_eq!(
      Ok(None),
      action_cache
        .load_process_result(new_cacheable_perl.clone())
        .wait()
    );
    let new_caching_runner =
      make_caching_runner(base_runner.clone(), action_cache.clone(), Some(new_key));
    let new_process_result = new_caching_runner.run(random_perl.clone()).wait().unwrap();
    assert_eq!(0, new_process_result.exit_code);
    // The new `cache_key_gen_version` is propagated to the requests made against the
    // CachingCommandRunner.
    assert_eq!(
      new_process_result.clone().into_cacheable(),
      action_cache
        .load_process_result(new_cacheable_perl)
        .wait()
        .unwrap()
        .unwrap()
    );
    let new_perl_number = String::from_utf8(new_process_result.stdout.deref().to_vec())
      .unwrap()
      .parse::<f64>()
      .unwrap();
    // The output of the rand(10) call in the perl invocation is different, because the process
    // execution wasn't cached.
    assert!(new_perl_number != perl_number);
    // Make sure that changing the cache key string from non-None to non-None also invalidates the
    // process result.
    let second_string_key = "yy".to_string();
    let second_cache_string_perl = CacheableExecuteProcessRequest {
      req: random_perl.clone(),
      cache_key_gen_version: Some(second_string_key.clone()),
    };
    assert_eq!(
      Ok(None),
      action_cache
        .load_process_result(second_cache_string_perl.clone())
        .wait()
    );
    let second_string_caching_runner = make_caching_runner(
      base_runner.clone(),
      action_cache.clone(),
      Some(second_string_key),
    );
    let second_string_process_result = second_string_caching_runner
      .run(random_perl)
      .wait()
      .unwrap();
    assert_eq!(0, second_string_process_result.exit_code);
    assert_eq!(
      second_string_process_result.clone().into_cacheable(),
      action_cache
        .load_process_result(second_cache_string_perl)
        .wait()
        .unwrap()
        .unwrap()
    );
    let second_string_perl_number =
      String::from_utf8(second_string_process_result.stdout.deref().to_vec())
        .unwrap()
        .parse::<f64>()
        .unwrap();
    // The new result is distinct from all the previously cached invocations.
    assert!(second_string_perl_number != perl_number);
    assert!(second_string_perl_number != new_perl_number);
  }

  fn output_only_process_request(argv: Vec<String>) -> ExecuteProcessRequest {
    ExecuteProcessRequest {
      argv,
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "write some output".to_string(),
      jdk_home: None,
    }
  }

  fn cache_in_dir(
    store_dir: &Path,
    work_dir: &Path,
  ) -> (fs::Store, crate::local::CommandRunner, ActionCache) {
    let pool = Arc::new(fs::ResettablePool::new("test-pool-".to_owned()));
    let store = fs::Store::local_only(store_dir, pool.clone()).unwrap();
    let action_cache = ActionCache::new(store.clone());
    let base_runner =
      crate::local::CommandRunner::new(store.clone(), pool, work_dir.to_path_buf(), true);
    (store, base_runner, action_cache)
  }

  fn make_caching_runner(
    base_runner: crate::local::CommandRunner,
    action_cache: ActionCache,
    cache_key_gen_version: Option<String>,
  ) -> CachingCommandRunner {
    CachingCommandRunner::new(
      Box::new(base_runner) as Box<dyn CommandRunner>,
      Box::new(action_cache)
        as Box<
          dyn ImmediateExecutionCache<
            CacheableExecuteProcessRequest,
            CacheableExecuteProcessResult,
          >,
        >,
      cache_key_gen_version,
    )
  }
}
