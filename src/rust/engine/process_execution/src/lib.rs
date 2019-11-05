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
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

#[macro_use]
extern crate derivative;

use boxfuture::BoxFuture;
use bytes::Bytes;
use std::collections::{BTreeMap, BTreeSet};
use std::convert::TryFrom;
use std::ops::AddAssign;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use store::UploadSummary;
use workunit_store::WorkUnitStore;

use async_semaphore::AsyncSemaphore;
use hashing::Digest;

pub mod cache;
#[cfg(test)]
mod cache_tests;

pub mod local;
#[cfg(test)]
mod local_tests;

pub mod remote;
#[cfg(test)]
pub mod remote_tests;

pub mod speculate;
#[cfg(test)]
mod speculate_tests;

pub mod nailgun;

extern crate uname;

#[derive(PartialOrd, Ord, Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub enum Platform {
  Darwin,
  Linux,
  None,
}

impl Platform {
  pub fn current_platform() -> Result<Platform, String> {
    let platform_info = uname::uname().expect("Failed to get local platform info!");
    match platform_info {
      uname::Info { ref sysname, .. } if sysname.to_lowercase() == "darwin" => Ok(Platform::Darwin),
      uname::Info { ref sysname, .. } if sysname.to_lowercase() == "linux" => Ok(Platform::Linux),
      uname::Info { ref sysname, .. } => Err(format!("Found unknown system name {}", sysname)),
    }
  }
}

impl TryFrom<&String> for Platform {
  type Error = String;
  ///
  /// This is a helper method to convert values from the python/engine/platform.py::Platform enum,
  /// which have been serialized, into the rust Platform enum.
  ///
  fn try_from(variant_candidate: &String) -> Result<Self, Self::Error> {
    match variant_candidate.as_ref() {
      "darwin" => Ok(Platform::Darwin),
      "linux" => Ok(Platform::Linux),
      "none" => Ok(Platform::None),
      other => Err(format!(
        "Unknown, platform {:?} encountered in parsing",
        other
      )),
    }
  }
}

impl From<Platform> for String {
  fn from(platform: Platform) -> String {
    match platform {
      Platform::Linux => "linux".to_string(),
      Platform::Darwin => "osx".to_string(),
      Platform::None => "none".to_string(),
    }
  }
}

///
/// A process to be executed.
///
#[derive(Derivative, Clone, Debug, Eq)]
#[derivative(PartialEq, Hash)]
pub struct ExecuteProcessRequest {
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

  pub input_files: hashing::Digest,

  pub output_files: BTreeSet<PathBuf>,

  pub output_directories: BTreeSet<PathBuf>,

  pub timeout: std::time::Duration,

  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  pub description: String,

  // This will be materialized for local ExecuteProcessRequest only.
  // Eventually we want to remove this.
  // Context: https://github.com/pantsbuild/pants/issues/8314
  // Think twice before using it.
  #[derivative(PartialEq = "ignore", Hash = "ignore")]
  pub unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule:
    hashing::Digest,
  ///
  /// If present, a symlink will be created at .jdk which points to this directory for local
  /// execution, or a system-installed JDK (ignoring the value of the present Some) for remote
  /// execution.
  ///
  /// This is some technical debt we should clean up;
  /// see https://github.com/pantsbuild/pants/issues/6416.
  ///
  pub jdk_home: Option<PathBuf>,
  pub target_platform: Platform,

  pub is_nailgunnable: bool,
}

impl TryFrom<MultiPlatformExecuteProcessRequest> for ExecuteProcessRequest {
  type Error = String;

  fn try_from(req: MultiPlatformExecuteProcessRequest) -> Result<Self, Self::Error> {
    match req.0.get(&(Platform::None, Platform::None)) {
      Some(crossplatform_req) => Ok(crossplatform_req.clone()),
      None => Err(String::from(
        "Cannot coerce to a simple ExecuteProcessRequest, no cross platform request exists.",
      )),
    }
  }
}

///
/// A container of platform constrained processes.
///
#[derive(Derivative, Clone, Debug, Eq, PartialEq, Hash)]
pub struct MultiPlatformExecuteProcessRequest(
  pub BTreeMap<(Platform, Platform), ExecuteProcessRequest>,
);

impl From<ExecuteProcessRequest> for MultiPlatformExecuteProcessRequest {
  fn from(req: ExecuteProcessRequest) -> Self {
    MultiPlatformExecuteProcessRequest(
      vec![((Platform::None, Platform::None), req)]
        .into_iter()
        .collect(),
    )
  }
}

///
/// Metadata surrounding an ExecuteProcessRequest which factors into its cache key when cached
/// externally from the engine graph (e.g. when using remote execution or an external process
/// cache).
///
#[derive(Clone, Debug)]
pub struct ExecuteProcessRequestMetadata {
  pub instance_name: Option<String>,
  pub cache_key_gen_version: Option<String>,
  pub platform_properties: Vec<(String, String)>,
}

///
/// The result of running a process.
///
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FallibleExecuteProcessResult {
  pub stdout: Bytes,
  pub stderr: Bytes,
  pub exit_code: i32,

  // It's unclear whether this should be a Snapshot or a digest of a Directory. A Directory digest
  // is handy, so let's try that out for now.
  pub output_directory: hashing::Digest,

  pub execution_attempts: Vec<ExecutionStats>,
}

#[cfg(test)]
impl FallibleExecuteProcessResult {
  pub fn without_execution_attempts(mut self) -> Self {
    self.execution_attempts = vec![];
    self
  }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ExecutionStats {
  uploaded_bytes: usize,
  uploaded_file_count: usize,
  upload: Duration,
  remote_queue: Option<Duration>,
  remote_input_fetch: Option<Duration>,
  remote_execution: Option<Duration>,
  remote_output_store: Option<Duration>,
  was_cache_hit: bool,
}

impl AddAssign<UploadSummary> for ExecutionStats {
  fn add_assign(&mut self, summary: UploadSummary) {
    self.uploaded_file_count += summary.uploaded_file_count;
    self.uploaded_bytes += summary.uploaded_file_bytes;
    self.upload += summary.upload_wall_time;
  }
}

#[derive(Clone, Default)]
pub struct Context {
  pub workunit_store: WorkUnitStore,
  pub build_id: String,
}

pub trait CommandRunner: Send + Sync {
  ///
  /// Submit a request for execution on the underlying runtime, and return
  /// a future for it.
  ///
  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String>;

  ///
  /// Given a multi platform request which may have some platform
  /// constraints determine if any of the requests contained within are compatible
  /// with the current command runners platform configuration. If so return the
  /// first candidate that will be run if the multi platform request is submitted to
  /// `fn run(..)`
  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest>;

  fn num_waiters(&self) -> usize {
    panic!("This method is abstract and not implemented for this type")
  }
}

// TODO(#8513) possibly move to the MEPR struct, or to the hashing crate?
pub fn digest(
  req: MultiPlatformExecuteProcessRequest,
  metadata: &ExecuteProcessRequestMetadata,
) -> Digest {
  let mut hashes: Vec<String> = req
    .0
    .values()
    .map(|ref epr| crate::remote::make_execute_request(epr, metadata.clone()).unwrap())
    .map(|(_a, _b, er)| er.get_action_digest().get_hash().to_string())
    .collect();
  hashes.sort();
  Digest::of_bytes(
    hashes
      .iter()
      .fold(String::new(), |mut acc, hash| {
        acc.push_str(&hash);
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

impl CommandRunner for BoundedCommandRunner {
  fn num_waiters(&self) -> usize {
    self.inner.1.num_waiters()
  }

  fn run(
    &self,
    req: MultiPlatformExecuteProcessRequest,
    context: Context,
  ) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let inner = self.inner.clone();
    self
      .inner
      .1
      .with_acquired(move || inner.0.run(req, context))
  }

  fn extract_compatible_request(
    &self,
    req: &MultiPlatformExecuteProcessRequest,
  ) -> Option<ExecuteProcessRequest> {
    self.inner.0.extract_compatible_request(&req)
  }
}

impl From<Box<BoundedCommandRunner>> for Arc<dyn CommandRunner> {
  fn from(command_runner: Box<BoundedCommandRunner>) -> Arc<dyn CommandRunner> {
    Arc::new(*command_runner)
  }
}

#[cfg(test)]
mod tests;
