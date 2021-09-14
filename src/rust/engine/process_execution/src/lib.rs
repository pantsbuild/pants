// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]
#![type_length_limit = "43757804"]
#[macro_use]
extern crate derivative;

use std::collections::{BTreeMap, BTreeSet};
use std::convert::TryFrom;
use std::path::PathBuf;
use std::sync::Arc;

pub use log::Level;

use async_semaphore::AsyncSemaphore;
use async_trait::async_trait;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use hashing::{Digest, EMPTY_FINGERPRINT};
use remexec::ExecutedActionMetadata;
use serde::{Deserialize, Serialize};
use workunit_store::{RunningWorkunit, WorkunitStore};

pub mod cache;
#[cfg(test)]
mod cache_tests;

pub mod local;
#[cfg(test)]
mod local_tests;

pub mod remote;
#[cfg(test)]
pub mod remote_tests;

pub mod remote_cache;
#[cfg(test)]
mod remote_cache_tests;

pub mod nailgun;

pub mod named_caches;

extern crate uname;

pub use crate::named_caches::{CacheDest, CacheName, NamedCaches};
use concrete_time::{Duration, TimeSpan};
use fs::RelativePath;

#[derive(PartialOrd, Ord, Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[allow(non_camel_case_types)]
pub enum Platform {
  Macos_x86_64,
  Macos_arm64,
  Linux_x86_64,
  Linux_arm64,
}

impl Platform {
  pub fn current() -> Result<Platform, String> {
    let platform_info =
      uname::uname().map_err(|_| "Failed to get local platform info!".to_string())?;
    match platform_info {
      uname::Info {
        ref sysname,
        ref machine,
        ..
      } if sysname.to_lowercase() == "linux" && machine.to_lowercase() == "x86_64" => {
        Ok(Platform::Linux_x86_64)
      }
      uname::Info {
        ref sysname,
        ref machine,
        ..
      } if sysname.to_lowercase() == "linux" && machine.to_lowercase() == "aarch64" => {
        Ok(Platform::Linux_arm64)
      }
      uname::Info {
        ref sysname,
        ref machine,
        ..
      } if sysname.to_lowercase() == "darwin" && machine.to_lowercase() == "arm64" => {
        Ok(Platform::Macos_arm64)
      }
      uname::Info {
        ref sysname,
        ref machine,
        ..
      } if sysname.to_lowercase() == "darwin" && machine.to_lowercase() == "x86_64" => {
        Ok(Platform::Macos_x86_64)
      }
      uname::Info {
        ref sysname,
        ref machine,
        ..
      } => Err(format!(
        "Found unknown system/arch name pair {} {}",
        sysname, machine
      )),
    }
  }
}

impl From<Platform> for String {
  fn from(platform: Platform) -> String {
    match platform {
      Platform::Linux_x86_64 => "linux_x86_64".to_string(),
      Platform::Linux_arm64 => "linux_arm64".to_string(),
      Platform::Macos_arm64 => "macos_arm64".to_string(),
      Platform::Macos_x86_64 => "macos_x86_64".to_string(),
    }
  }
}

impl TryFrom<String> for Platform {
  type Error = String;
  fn try_from(variant_candidate: String) -> Result<Self, Self::Error> {
    match variant_candidate.as_ref() {
      "macos_arm64" => Ok(Platform::Macos_arm64),
      "macos_x86_64" => Ok(Platform::Macos_x86_64),
      "linux_x86_64" => Ok(Platform::Linux_x86_64),
      "linux_arm64" => Ok(Platform::Linux_arm64),
      other => Err(format!(
        "Unknown platform {:?} encountered in parsing",
        other
      )),
    }
  }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize)]
pub enum ProcessCacheScope {
  // Cached in all locations, regardless of success or failure.
  Always,
  // Cached in all locations, but only if the process exits successfully.
  Successful,
  // Cached only in memory (i.e. memoized in pantsd), but never persistently, regardless of
  // success vs. failure.
  PerRestartAlways,
  // Cached only in memory (i.e. memoized in pantsd), but never persistently, and only if
  // successful.
  PerRestartSuccessful,
  // Will run once per Session, i.e. once per run of Pants. This happens because the engine
  // de-duplicates identical work; the process is neither memoized in memory nor cached to disk.
  PerSession,
}

impl TryFrom<String> for ProcessCacheScope {
  type Error = String;
  fn try_from(variant_candidate: String) -> Result<Self, Self::Error> {
    match variant_candidate.to_lowercase().as_ref() {
      "always" => Ok(ProcessCacheScope::Always),
      "successful" => Ok(ProcessCacheScope::Successful),
      "per_restart_always" => Ok(ProcessCacheScope::PerRestartAlways),
      "per_restart_successful" => Ok(ProcessCacheScope::PerRestartSuccessful),
      "per_session" => Ok(ProcessCacheScope::PerSession),
      other => Err(format!("Unknown Process cache scope: {:?}", other)),
    }
  }
}

fn serialize_level<S: serde::Serializer>(level: &log::Level, s: S) -> Result<S::Ok, S::Error> {
  s.serialize_str(&level.to_string())
}

///
/// A process to be executed.
///
#[derive(Derivative, Clone, Debug, Eq, Serialize)]
#[derivative(PartialEq, Hash)]
pub struct Process {
  ///
  /// The arguments to execute.
  ///
  /// The first argument should be an absolute or relative path to the binary to execute.
  ///
  /// No PATH lookup will be performed unless a PATH environment variable is specified.
  ///
  /// No shell expansion will take place.
  ///
  pub argv: Vec<String>,
  ///
  /// The environment variables to set for the execution.
  ///
  /// No other environment variables will be set (except possibly for an empty PATH variable).
  ///
  pub env: BTreeMap<String, String>,

  ///
  /// A relative path to a directory existing in the `input_files` digest to execute the process
  /// from. Defaults to the `input_files` root.
  ///
  pub working_directory: Option<RelativePath>,

  pub input_files: hashing::Digest,

  pub output_files: BTreeSet<RelativePath>,

  pub output_directories: BTreeSet<RelativePath>,

  pub timeout: Option<std::time::Duration>,

  /// If not None, then if a BoundedCommandRunner executes this Process
  pub execution_slot_variable: Option<String>,

  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  pub description: String,

  // NB: We serialize with a function to avoid adding a serde dep to the logging crate.
  #[serde(serialize_with = "serialize_level")]
  pub level: log::Level,

  ///
  /// Declares that this process uses the given named caches (which might have associated config
  /// in the future) at the associated relative paths within its workspace. Cache names must
  /// contain only lowercase ascii characters or underscores.
  ///
  /// Caches are exposed to processes within their workspaces at the relative paths represented
  /// by the values of the dict. A process may optionally check for the existence of the relevant
  /// directory, and disable use of that cache if it has not been created by the executor
  /// (indicating a lack of support for this feature).
  ///
  /// These caches are globally shared and so must be concurrency safe: a consumer of the cache
  /// must never assume that it has exclusive access to the provided directory.
  ///
  pub append_only_caches: BTreeMap<CacheName, CacheDest>,

  ///
  /// If present, a symlink will be created at .jdk which points to this directory for local
  /// execution, or a system-installed JDK (ignoring the value of the present Some) for remote
  /// execution.
  ///
  /// This is some technical debt we should clean up;
  /// see https://github.com/pantsbuild/pants/issues/6416.
  ///
  pub jdk_home: Option<PathBuf>,

  pub platform_constraint: Option<Platform>,

  pub is_nailgunnable: bool,

  pub cache_scope: ProcessCacheScope,
}

impl Process {
  ///
  /// Constructs a Process with default values for most fields, after which the builder pattern can
  /// be used to set values.
  ///
  /// We use the more ergonomic (but possibly slightly slower) "move self for each builder method"
  /// pattern, so this method is only enabled for test usage: production usage should construct the
  /// Process struct wholesale. We can reconsider this if we end up with more production callsites
  /// that require partial options.
  ///
  #[cfg(test)]
  pub fn new(argv: Vec<String>) -> Process {
    Process {
      argv,
      env: BTreeMap::new(),
      working_directory: None,
      input_files: hashing::EMPTY_DIGEST,
      output_files: BTreeSet::new(),
      output_directories: BTreeSet::new(),
      timeout: None,
      description: "".to_string(),
      level: log::Level::Info,
      append_only_caches: BTreeMap::new(),
      jdk_home: None,
      platform_constraint: None,
      is_nailgunnable: false,
      execution_slot_variable: None,
      cache_scope: ProcessCacheScope::Successful,
    }
  }

  ///
  /// Replaces the environment for this process.
  ///
  pub fn env(mut self, env: BTreeMap<String, String>) -> Process {
    self.env = env;
    self
  }

  ///
  /// Replaces the output files for this process.
  ///
  pub fn output_files(mut self, output_files: BTreeSet<RelativePath>) -> Process {
    self.output_files = output_files;
    self
  }

  ///
  /// Replaces the output directories for this process.
  ///
  pub fn output_directories(mut self, output_directories: BTreeSet<RelativePath>) -> Process {
    self.output_directories = output_directories;
    self
  }

  ///
  /// Replaces the append only caches for this process.
  ///
  pub fn append_only_caches(
    mut self,
    append_only_caches: BTreeMap<CacheName, CacheDest>,
  ) -> Process {
    self.append_only_caches = append_only_caches;
    self
  }
}

impl TryFrom<MultiPlatformProcess> for Process {
  type Error = String;

  fn try_from(req: MultiPlatformProcess) -> Result<Self, Self::Error> {
    match req.0.get(&None) {
      Some(crossplatform_req) => Ok(crossplatform_req.clone()),
      None => Err(String::from(
        "Cannot coerce to a simple Process, no cross platform request exists.",
      )),
    }
  }
}

///
/// A container of platform constrained processes.
///
#[derive(Derivative, Clone, Debug, Eq, PartialEq, Hash)]
pub struct MultiPlatformProcess(pub BTreeMap<Option<Platform>, Process>);

impl MultiPlatformProcess {
  pub fn user_facing_name(&self) -> String {
    self
      .0
      .iter()
      .next()
      .map(|(_platforms, process)| process.description.clone())
      .unwrap_or_else(|| "<Unnamed process>".to_string())
  }

  pub fn workunit_level(&self) -> log::Level {
    self
      .0
      .iter()
      .next()
      .map(|(_platforms, process)| process.level)
      .unwrap_or(Level::Info)
  }
}

impl From<Process> for MultiPlatformProcess {
  fn from(proc: Process) -> Self {
    MultiPlatformProcess(vec![(None, proc)].into_iter().collect())
  }
}

///
/// Metadata surrounding an Process which factors into its cache key when cached
/// externally from the engine graph (e.g. when using remote execution or an external process
/// cache).
///
#[derive(Clone, Debug, Default)]
pub struct ProcessMetadata {
  pub instance_name: Option<String>,
  pub cache_key_gen_version: Option<String>,
  pub platform_properties: Vec<(String, String)>,
}

///
/// The result of running a process.
///
#[derive(Derivative, Clone, Debug, Eq)]
#[derivative(PartialEq, Hash)]
pub struct FallibleProcessResultWithPlatform {
  pub stdout_digest: Digest,
  pub stderr_digest: Digest,
  pub exit_code: i32,
  pub output_directory: hashing::Digest,
  pub platform: Platform,
  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  pub metadata: ProcessResultMetadata,
}

/// Metadata for a ProcessResult corresponding to the REAPI `ExecutedActionMetadata` proto. This
/// conversion is lossy, but the interesting parts are preserved.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessResultMetadata {
  /// The time from starting to completion, including preparing the chroot and cleanup.
  /// Corresponds to `worker_start_timestamp` and `worker_completed_timestamp` from
  /// `ExecutedActionMetadata`.
  ///
  /// NB: This is optional because the REAPI does not guarantee that it is returned.
  pub total_elapsed: Option<Duration>,
  /// The source of the result.
  pub source: ProcessResultSource,
}

impl ProcessResultMetadata {
  pub fn new(total_elapsed: Option<Duration>, source: ProcessResultSource) -> Self {
    ProcessResultMetadata {
      total_elapsed,
      source,
    }
  }

  pub fn new_from_metadata(metadata: ExecutedActionMetadata, source: ProcessResultSource) -> Self {
    let total_elapsed = match (
      metadata.worker_start_timestamp,
      metadata.worker_completed_timestamp,
    ) {
      (Some(started), Some(completed)) => TimeSpan::from_start_and_end(&started, &completed, "")
        .map(|span| span.duration)
        .ok(),
      _ => None,
    };
    Self {
      total_elapsed,
      source,
    }
  }

  /// How much faster a cache hit was than running the process again.
  ///
  /// This includes the overhead of setting up and cleaning up the process for execution, and it
  /// should include all overhead for the cache lookup.
  ///
  /// If the cache hit was slower than the original process, we return 0. Note that the cache hit
  /// may still have been faster than rerunning the process a second time, e.g. if speculation
  /// is used and the cache hit completed before the rerun; still, we cannot know how long the
  /// second run would have taken, so the best we can do is report 0.
  ///
  /// If the original process's execution time was not recorded, we return None because we
  /// cannot make a meaningful comparison.
  pub fn time_saved_from_cache(
    &self,
    cache_lookup: std::time::Duration,
  ) -> Option<std::time::Duration> {
    self.total_elapsed.and_then(|original_process| {
      let original_process: std::time::Duration = original_process.into();
      original_process
        .checked_sub(cache_lookup)
        .or_else(|| Some(std::time::Duration::new(0, 0)))
    })
  }
}

impl From<ProcessResultMetadata> for ExecutedActionMetadata {
  fn from(metadata: ProcessResultMetadata) -> ExecutedActionMetadata {
    let (total_start, total_end) = match metadata.total_elapsed {
      Some(elapsed) => {
        // Because we do not have the precise start time, we hardcode to starting at UNIX_EPOCH. We
        // only care about accurately preserving the duration.
        let start = prost_types::Timestamp {
          seconds: 0,
          nanos: 0,
        };
        let end = prost_types::Timestamp {
          seconds: elapsed.secs as i64,
          nanos: elapsed.nanos as i32,
        };
        (Some(start), Some(end))
      }
      None => (None, None),
    };
    ExecutedActionMetadata {
      worker_start_timestamp: total_start,
      worker_completed_timestamp: total_end,
      ..ExecutedActionMetadata::default()
    }
  }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcessResultSource {
  RanLocally,
  RanRemotely,
  HitLocally,
  HitRemotely,
}

#[derive(Clone)]
pub struct Context {
  workunit_store: WorkunitStore,
  build_id: String,
}

impl Default for Context {
  fn default() -> Self {
    Context {
      workunit_store: WorkunitStore::new(false),
      build_id: String::default(),
    }
  }
}

impl Context {
  pub fn new(workunit_store: WorkunitStore, build_id: String) -> Context {
    Context {
      workunit_store,
      build_id,
    }
  }
}

#[async_trait]
pub trait CommandRunner: Send + Sync {
  ///
  /// Submit a request for execution on the underlying runtime, and return
  /// a future for it.
  ///
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    req: MultiPlatformProcess,
  ) -> Result<FallibleProcessResultWithPlatform, String>;

  ///
  /// Given a multi platform request which may have some platform
  /// constraints determine if any of the requests contained within are compatible
  /// with the current command runners platform configuration. If so return the
  /// first candidate that will be run if the multi platform request is submitted to
  /// `fn run(..)`
  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process>;
}

// TODO(#8513) possibly move to the MEPR struct, or to the hashing crate?
pub fn digest(req: MultiPlatformProcess, metadata: &ProcessMetadata) -> Digest {
  let mut hashes: Vec<String> = req
    .0
    .values()
    .map(|process| crate::remote::make_execute_request(process, metadata.clone()).unwrap())
    .map(|(_a, _b, er)| {
      er.action_digest
        .map(|d| d.hash)
        .unwrap_or_else(|| EMPTY_FINGERPRINT.to_hex())
    })
    .collect();
  hashes.sort();
  Digest::of_bytes(
    hashes
      .iter()
      .fold(String::new(), |mut acc, hash| {
        acc.push_str(hash);
        acc
      })
      .as_bytes(),
  )
}

///
/// A CommandRunner wrapper that limits the number of concurrent requests.
///
#[derive(Clone)]
pub struct BoundedCommandRunner {
  inner: Arc<(Box<dyn CommandRunner>, AsyncSemaphore)>,
}

impl BoundedCommandRunner {
  pub fn new(inner: Box<dyn CommandRunner>, bound: usize) -> BoundedCommandRunner {
    BoundedCommandRunner {
      inner: Arc::new((inner, AsyncSemaphore::new(bound))),
    }
  }
}

#[async_trait]
impl CommandRunner for BoundedCommandRunner {
  async fn run(
    &self,
    context: Context,
    workunit: &mut RunningWorkunit,
    mut req: MultiPlatformProcess,
  ) -> Result<FallibleProcessResultWithPlatform, String> {
    let semaphore = self.inner.1.clone();
    let inner = self.inner.clone();
    let blocking_token = workunit.blocking();
    semaphore
      .with_acquired(|concurrency_id| {
        log::debug!(
          "Running {} under semaphore with concurrency id: {}",
          req.user_facing_name(),
          concurrency_id
        );
        std::mem::drop(blocking_token);

        for (_, process) in req.0.iter_mut() {
          if let Some(ref execution_slot_env_var) = process.execution_slot_variable {
            let execution_slot = format!("{}", concurrency_id);
            process
              .env
              .insert(execution_slot_env_var.clone(), execution_slot);
          }
        }

        inner.0.run(context, workunit, req)
      })
      .await
  }

  fn extract_compatible_request(&self, req: &MultiPlatformProcess) -> Option<Process> {
    self.inner.0.extract_compatible_request(req)
  }
}

impl From<Box<BoundedCommandRunner>> for Arc<dyn CommandRunner> {
  fn from(command_runner: Box<BoundedCommandRunner>) -> Arc<dyn CommandRunner> {
    Arc::new(*command_runner)
  }
}

#[derive(Clone, Copy, Debug, PartialEq, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum RemoteCacheWarningsBehavior {
  Ignore,
  FirstOnly,
  Backoff,
}

#[cfg(test)]
mod tests;
