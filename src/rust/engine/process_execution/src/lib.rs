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
#![allow(
  clippy::new_without_default,
  clippy::new_ret_no_self
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use boxfuture::BoxFuture;
use bytes::Bytes;
use std::collections::{BTreeMap, BTreeSet};
use std::ops::AddAssign;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use async_semaphore::AsyncSemaphore;

pub mod local;
pub mod remote;

///
/// A process to be executed.
///
#[derive(Clone, Debug, Eq, Hash, PartialEq)]
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

  pub description: String,

  ///
  /// If present, a symlink will be created at .jdk which points to this directory for local
  /// execution, or a system-installed JDK (ignoring the value of the present Some) for remote
  /// execution.
  ///
  /// This is some technical debt we should clean up;
  /// see https://github.com/pantsbuild/pants/issues/6416.
  ///
  pub jdk_home: Option<PathBuf>,
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

impl AddAssign<fs::UploadSummary> for ExecutionStats {
  fn add_assign(&mut self, summary: fs::UploadSummary) {
    self.uploaded_file_count += summary.uploaded_file_count;
    self.uploaded_bytes += summary.uploaded_file_bytes;
    self.upload += summary.upload_wall_time;
  }
}

pub trait CommandRunner: Send + Sync {
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String>;
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
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let inner = self.inner.clone();
    self.inner.1.with_acquired(move || inner.0.run(req))
  }
}
