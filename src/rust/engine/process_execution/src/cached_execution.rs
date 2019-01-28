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

use fs::{File, PathStat};
use hashing::{Digest, Fingerprint};

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

/// ???/why is this "cacheable"?
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

/// ???
pub enum OutputDirWrapping {
  Direct,
  TopLevelWrapped,
}

/// ???/it's called "immediate" because it's a best-effort thing located locally (???)
pub trait ImmediateExecutionCache<ProcessRequest, ProcessResult>: Send + Sync {
  fn record_process_result(
    &self,
    req: &ProcessRequest,
    res: &ProcessResult,
  ) -> BoxFuture<(), String>;

  fn load_process_result(&self, req: &ProcessRequest) -> BoxFuture<Option<ProcessResult>, String>;
}

/// ???
#[derive(Clone)]
pub struct ActionSerializer {
  store: fs::Store,
}

impl ActionSerializer {
  pub fn new(store: fs::Store) -> Self {
    ActionSerializer { store }
  }

  fn extract_digest(
    digest: &bazel_protos::build::bazel::remote::execution::v2::Digest,
  ) -> Result<Digest, String> {
    let fingerprint = Fingerprint::from_hex_string(&digest.hash)?;
    Ok(Digest(fingerprint, digest.size_bytes as usize))
  }

  pub fn convert_digest(
    digest: &Digest,
  ) -> bazel_protos::build::bazel::remote::execution::v2::Digest {
    let Digest(fingerprint, len) = digest;
    bazel_protos::build::bazel::remote::execution::v2::Digest {
      hash: fingerprint.to_hex(),
      size_bytes: *len as i64,
    }
  }

  fn make_command(
    req: &CacheableExecuteProcessRequest,
  ) -> Result<bazel_protos::build::bazel::remote::execution::v2::Command, String> {
    let CacheableExecuteProcessRequest {
      req,
      cache_key_gen_version,
    } = req;
    let arguments = req.argv.clone();

    if req.env.contains_key(CACHE_KEY_GEN_VERSION_ENV_VAR_NAME) {
      return Err(format!(
        "Cannot set env var with name {} as that is reserved for internal use by pants",
        CACHE_KEY_GEN_VERSION_ENV_VAR_NAME
      ));
    }
    let mut env_var_pairs: Vec<(String, String)> = req.env.clone().into_iter().collect();
    if let Some(cache_key_gen_version) = cache_key_gen_version {
      env_var_pairs.push((
        CACHE_KEY_GEN_VERSION_ENV_VAR_NAME.to_string(),
        cache_key_gen_version.to_string(),
      ));
    }
    let environment_variables: Vec<_> = env_var_pairs
      .into_iter()
      .map(|(name, value)| {
        bazel_protos::build::bazel::remote::execution::v2::command::EnvironmentVariable {
          name,
          value,
        }
      })
      .collect();

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

    // Ideally, the JDK would be brought along as part of the input directory, but we don't currently
    // have support for that. The platform with which we're experimenting for remote execution
    // supports this property, and will symlink .jdk to a system-installed JDK:
    // https://github.com/twitter/scoot/pull/391
    let platform = if req.jdk_home.is_some() {
      // This really should be req.jdk_home.map(|_| {...}), but that gives "cannot move out of
      // borrowed content".
      Some(
        bazel_protos::build::bazel::remote::execution::v2::Platform {
          properties: vec![
            bazel_protos::build::bazel::remote::execution::v2::platform::Property {
              name: "JDK_SYMLINK".to_owned(),
              value: ".jdk".to_owned(),
            },
          ],
        },
      )
    } else {
      None
    };

    Ok(bazel_protos::build::bazel::remote::execution::v2::Command {
      arguments,
      environment_variables,
      output_files,
      output_directories,
      platform,
      working_directory: "".to_owned(),
    })
  }

  pub fn encode_command_proto(
    command: &bazel_protos::build::bazel::remote::execution::v2::Command,
  ) -> Result<Bytes, String> {
    fs::Store::encode_proto(command)
      .map_err(|e| format!("Error serializing Command proto {:?}: {:?}", command, e))
  }

  /// ???/having the Command is necessary for making an ExecuteRequest proto, which we don't need in
  /// this file.
  pub fn make_action_with_command(
    req: &CacheableExecuteProcessRequest,
  ) -> Result<
    (
      bazel_protos::build::bazel::remote::execution::v2::Action,
      bazel_protos::build::bazel::remote::execution::v2::Command,
    ),
    String,
  > {
    let command = Self::make_command(&req)?;
    let command_proto_bytes = Self::encode_command_proto(&command)?;
    let action = bazel_protos::build::bazel::remote::execution::v2::Action {
      command_digest: Some(Self::convert_digest(&fs::Store::digest_bytes(
        &command_proto_bytes,
      ))),
      input_root_digest: Some(Self::convert_digest(&req.req.input_files)),
      ..bazel_protos::build::bazel::remote::execution::v2::Action::default()
    };
    Ok((action, command))
  }

  fn extract_stdout(
    &self,
    result: &bazel_protos::build::bazel::remote::execution::v2::ActionResult,
  ) -> BoxFuture<Bytes, String> {
    if let Some(ref stdout_digest) = result.stdout_digest {
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
      let stdout_raw = Bytes::from(result.stdout_raw.clone());
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
    result: &bazel_protos::build::bazel::remote::execution::v2::ActionResult,
  ) -> BoxFuture<Bytes, String> {
    if let Some(ref stderr_digest) = result.stderr_digest {
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
      let stderr_raw = Bytes::from(result.stderr_raw.clone());
      let stderr_copy = stderr_raw.clone();
      self
        .store
        .store_file_bytes(stderr_raw, true)
        .map_err(move |error| format!("Error storing raw stderr: {:?}", error))
        .map(|_| stderr_copy)
        .to_boxed()
    }
  }

  fn extract_output_files_with_single_containing_directory(
    result: &bazel_protos::build::bazel::remote::execution::v2::ActionResult,
  ) -> Result<Digest, String> {
    let invalid_containing_dir = || {
      format!("Error: invalid output directory for result {:?}. An process execution extracted as an ActionResult from the process execution cache must will always contain a single top-level directory with the path \"\".",
              result)
    };

    if result.output_files.is_empty() && result.output_directories.len() == 1 {
      // A single directory (with a provided digest), which should be at the path "".
      let dir = result.output_directories.last().unwrap();
      if dir.path.is_empty() {
        let proto_digest = dir.tree_digest.clone().unwrap();
        Self::extract_digest(&proto_digest)
      } else {
        Err(invalid_containing_dir())
      }
    } else {
      Err(invalid_containing_dir())
    }
  }

  fn extract_output_files(
    &self,
    result: &bazel_protos::build::bazel::remote::execution::v2::ActionResult,
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

  pub fn convert_request_to_action(
    req: &CacheableExecuteProcessRequest,
  ) -> Result<bazel_protos::build::bazel::remote::execution::v2::Action, String> {
    let (action, _) = Self::make_action_with_command(req)?;
    Ok(action)
  }

  pub fn convert_result_to_action_result(
    res: &CacheableExecuteProcessResult,
  ) -> bazel_protos::build::bazel::remote::execution::v2::ActionResult {
    bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      output_files: vec![],
      output_directories: vec![
        bazel_protos::build::bazel::remote::execution::v2::OutputDirectory {
          path: "".to_string(),
          tree_digest: Some(Self::convert_digest(&res.output_directory)),
        },
      ],
      exit_code: res.exit_code,
      stdout_raw: res.stdout.to_vec(),
      stdout_digest: Some(Self::convert_digest(&fs::Store::digest_bytes(&res.stdout))),
      stderr_raw: res.stderr.to_vec(),
      stderr_digest: Some(Self::convert_digest(&fs::Store::digest_bytes(&res.stderr))),
      execution_metadata: None,
    }
  }

  pub fn extract_action_result(
    &self,
    res: &bazel_protos::build::bazel::remote::execution::v2::ActionResult,
    wrapping: OutputDirWrapping,
  ) -> BoxFuture<CacheableExecuteProcessResult, String> {
    let exit_code = res.exit_code;
    let extracted_output_files = match wrapping {
      OutputDirWrapping::Direct => self.extract_output_files(&res),
      OutputDirWrapping::TopLevelWrapped => future::result(
        Self::extract_output_files_with_single_containing_directory(&res),
      )
      .to_boxed(),
    };
    self
      .extract_stdout(&res)
      .join(self.extract_stderr(&res))
      .join(extracted_output_files)
      .map(
        move |((stdout, stderr), output_directory)| CacheableExecuteProcessResult {
          stdout,
          stderr,
          exit_code,
          output_directory,
        },
      )
      .to_boxed()
  }
}

impl ImmediateExecutionCache<CacheableExecuteProcessRequest, CacheableExecuteProcessResult>
  for ActionSerializer
{
  fn record_process_result(
    &self,
    req: &CacheableExecuteProcessRequest,
    res: &CacheableExecuteProcessResult,
  ) -> BoxFuture<(), String> {
    let action_request = Self::convert_request_to_action(&req);
    let action_result = Self::convert_result_to_action_result(&res);
    let store = self.store.clone();
    // TODO: I wish there was a shorthand syntax to extract multiple fields from a reference to a
    // struct while cloning them.
    let stdout = res.stdout.clone();
    let stderr = res.stderr.clone();
    future::result(action_request)
      .and_then(move |action_request| {
        store
          .store_file_bytes(stdout, true)
          .join(store.store_file_bytes(stderr, true))
          .and_then(move |(_, _)| {
            // NB: We wait until the stdout and stderr digests have been successfully recorded, so
            // that we don't later attempt to read digests in the `action_result` which don't exist.
            store.record_process_result(&action_request, &action_result)
          })
          .to_boxed()
      })
      .to_boxed()
  }

  fn load_process_result(
    &self,
    req: &CacheableExecuteProcessRequest,
  ) -> BoxFuture<Option<CacheableExecuteProcessResult>, String> {
    let store = self.store.clone();
    let cache = self.clone();
    future::result(Self::convert_request_to_action(req))
      .and_then(move |action_proto| store.load_process_result(&action_proto))
      .and_then(move |maybe_action_result| match maybe_action_result {
        Some(action_result) => cache
          // NB: FallibleExecuteProcessResult always wraps everything in a *single* output
          // directory, which is then converted into an OutputDirectory for the ActionResult proto
          // at the path "" in convert_result_to_action_result(), so we have to pull the contents
          // out of that single dir with the path "".
          .extract_action_result(&action_result, OutputDirWrapping::TopLevelWrapped)
          .map(Some)
          .to_boxed(),
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
    let action_serializer = ActionSerializer::new(store);
    let boxed_cache = Box::new(action_serializer)
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
      .load_process_result(&cacheable_request)
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
              .record_process_result(&cacheable_request, &cacheable_process_result)
              .map(move |()| {
                debug!(
                  "request {:?} should now be cached as {:?}",
                  &cacheable_request, &cacheable_process_result,
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
    ActionSerializer, CacheableExecuteProcessRequest, CacheableExecuteProcessResult,
    CachingCommandRunner, CommandRunner, ExecuteProcessRequest, FallibleExecuteProcessResult,
    ImmediateExecutionCache,
  };
  use crate::local::testutils::find_bash;
  use futures::future::Future;
  use hashing::{Digest, Fingerprint};
  use std::collections::{BTreeMap, BTreeSet};
  use std::ops::Deref;
  use std::path::Path;
  use std::path::PathBuf;
  use std::sync::Arc;
  use std::time::Duration;
  use tempfile::TempDir;
  use testutil::data::{TestData, TestDirectory};
  use testutil::owned_string_vec;

  #[test]
  fn encode_action() {
    let input_directory = TestDirectory::containing_roland();
    let req = ExecuteProcessRequest {
      argv: owned_string_vec(&["/bin/echo", "yo"]),
      env: vec![("SOME".to_owned(), "value".to_owned())]
        .into_iter()
        .collect(),
      input_files: input_directory.digest(),
      // Intentionally poorly sorted:
      output_files: vec!["path/to/file", "other/file"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      output_directories: vec!["directory/name"]
        .into_iter()
        .map(PathBuf::from)
        .collect(),
      timeout: Duration::from_millis(1000),
      description: "some description".to_owned(),
      jdk_home: None,
    };

    let want_action = bazel_protos::build::bazel::remote::execution::v2::Action {
      command_digest: Some(ActionSerializer::convert_digest(&Digest(
        Fingerprint::from_hex_string(
          "cc4ddd3085aaffbe0abce22f53b30edbb59896bb4a4f0d76219e48070cd0afe1",
        )
        .unwrap(),
        72,
      ))),
      input_root_digest: Some(ActionSerializer::convert_digest(&input_directory.digest())),
      ..Default::default()
    };

    assert_eq!(
      Ok(want_action),
      ActionSerializer::convert_request_to_action(&CacheableExecuteProcessRequest::new(req, None))
    );
  }

  #[test]
  fn encode_empty_action_result() {
    let testdata_empty = TestData::empty();

    let empty_proto_digest = bazel_protos::build::bazel::remote::execution::v2::Digest {
      hash: fs::EMPTY_DIGEST.0.to_hex(),
      size_bytes: fs::EMPTY_DIGEST.1 as i64,
    };

    let want_action_result = bazel_protos::build::bazel::remote::execution::v2::ActionResult {
      output_files: vec![],
      output_directories: vec![
        bazel_protos::build::bazel::remote::execution::v2::OutputDirectory {
          path: "".to_string(),
          tree_digest: Some(empty_proto_digest.clone()),
        },
      ],
      exit_code: 0,
      stdout_raw: vec![],
      stdout_digest: Some(empty_proto_digest.clone()),
      stderr_raw: vec![],
      stderr_digest: Some(empty_proto_digest.clone()),
      execution_metadata: None,
    };

    let empty_result = FallibleExecuteProcessResult {
      stdout: testdata_empty.bytes(),
      stderr: testdata_empty.bytes(),
      exit_code: 0,
      output_directory: fs::EMPTY_DIGEST,
      execution_attempts: vec![],
    };

    assert_eq!(
      want_action_result,
      ActionSerializer::convert_result_to_action_result(&empty_result.into_cacheable())
    );
  }

  #[test]
  #[cfg(unix)]
  fn cached_process_execution_stdout() {
    let random_perl = output_only_process_request(owned_string_vec(&[
      "/usr/bin/perl",
      "-e",
      "print(rand(10))",
    ]));
    let store_dir = TempDir::new().unwrap();
    let work_dir = TempDir::new().unwrap();
    let (_, base_runner, action_serializer) = cache_in_dir(store_dir.path(), work_dir.path());
    let cacheable_perl = CacheableExecuteProcessRequest {
      req: random_perl.clone(),
      cache_key_gen_version: None,
    };
    assert_eq!(
      Ok(None),
      action_serializer
        .load_process_result(&cacheable_perl)
        .wait()
    );
    let caching_runner = make_caching_runner(base_runner.clone(), action_serializer.clone(), None);
    let process_result = caching_runner.run(random_perl.clone()).wait().unwrap();
    // The process run again without caching is different.
    let base_process_result = base_runner.run(random_perl.clone()).wait().unwrap();
    assert!(base_process_result != process_result);
    assert_eq!(0, process_result.exit_code);
    // A "cacheable" process execution result won't have e.g. the number of attempts that the
    // process was tried, for idempotency, but everything else should be the same.
    assert_eq!(
      process_result.clone().into_cacheable(),
      action_serializer
        .load_process_result(&cacheable_perl)
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
      action_serializer
        .load_process_result(&new_cacheable_perl)
        .wait()
    );
    let new_caching_runner = make_caching_runner(
      base_runner.clone(),
      action_serializer.clone(),
      Some(new_key),
    );
    let new_process_result = new_caching_runner.run(random_perl.clone()).wait().unwrap();
    assert_eq!(0, new_process_result.exit_code);
    // The new `cache_key_gen_version` is propagated to the requests made against the
    // CachingCommandRunner.
    assert_eq!(
      new_process_result.clone().into_cacheable(),
      action_serializer
        .load_process_result(&new_cacheable_perl)
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
      action_serializer
        .load_process_result(&second_cache_string_perl)
        .wait()
    );
    let second_string_caching_runner = make_caching_runner(
      base_runner.clone(),
      action_serializer.clone(),
      Some(second_string_key),
    );
    let second_string_process_result = second_string_caching_runner
      .run(random_perl)
      .wait()
      .unwrap();
    assert_eq!(0, second_string_process_result.exit_code);
    assert_eq!(
      second_string_process_result.clone().into_cacheable(),
      action_serializer
        .load_process_result(&second_cache_string_perl)
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

  #[test]
  #[cfg(unix)]
  fn cached_process_execution_output_files() {
    let make_file = ExecuteProcessRequest {
      argv: vec![
        find_bash(),
        "-c".to_owned(),
        "/usr/bin/perl -e 'print(rand(10))' > wow.txt".to_string(),
      ],
      env: BTreeMap::new(),
      input_files: fs::EMPTY_DIGEST,
      output_files: vec!["wow.txt"].into_iter().map(PathBuf::from).collect(),
      output_directories: BTreeSet::new(),
      timeout: Duration::from_millis(1000),
      description: "make a nondeterministic file".to_string(),
      jdk_home: None,
    };
    let store_dir = TempDir::new().unwrap();
    let work_dir = TempDir::new().unwrap();
    let (_, base_runner, action_serializer) = cache_in_dir(store_dir.path(), work_dir.path());
    let cacheable_make_file = CacheableExecuteProcessRequest {
      req: make_file.clone(),
      cache_key_gen_version: None,
    };
    assert_eq!(
      Ok(None),
      action_serializer
        .load_process_result(&cacheable_make_file)
        .wait()
    );
    let caching_runner = make_caching_runner(base_runner.clone(), action_serializer.clone(), None);
    let base_process_result = base_runner.run(make_file.clone()).wait().unwrap();
    let process_result = caching_runner.run(make_file.clone()).wait().unwrap();
    // The process run again without caching is different.
    assert!(base_process_result != process_result);
    assert_eq!(0, process_result.exit_code);
    assert_eq!(
      process_result.clone().into_cacheable(),
      action_serializer
        .load_process_result(&cacheable_make_file)
        .wait()
        .unwrap()
        .unwrap()
    );
    let second_process_result = caching_runner.run(make_file.clone()).wait().unwrap();
    assert_eq!(second_process_result, process_result);
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
  ) -> (fs::Store, crate::local::CommandRunner, ActionSerializer) {
    let pool = Arc::new(fs::ResettablePool::new("test-pool-".to_owned()));
    let store = fs::Store::local_only(store_dir, pool.clone()).unwrap();
    let action_serializer = ActionSerializer::new(store.clone());
    let base_runner =
      crate::local::CommandRunner::new(store.clone(), pool, work_dir.to_path_buf(), true);
    (store, base_runner, action_serializer)
  }

  fn make_caching_runner(
    base_runner: crate::local::CommandRunner,
    action_serializer: ActionSerializer,
    cache_key_gen_version: Option<String>,
  ) -> CachingCommandRunner {
    CachingCommandRunner::new(
      Box::new(base_runner) as Box<dyn CommandRunner>,
      Box::new(action_serializer)
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
