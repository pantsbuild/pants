// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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

use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use futures::future::{self, Future};
use std::collections::{BTreeMap, BTreeSet};
use std::ops::AddAssign;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use async_semaphore::AsyncSemaphore;

pub mod cached_execution;
pub mod local;
pub mod remote;
pub use crate::cached_execution::{
  ActionCache, BazelProtosProcessExecutionCodec, ImmediateExecutionCache,
  SerializableProcessExecutionCodec,
};

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

/// ???/DON'T LET THE `cache_key_gen_version` BECOME A KITCHEN SINK!!!
#[derive(Clone)]
pub struct CacheableExecuteProcessRequest {
  req: ExecuteProcessRequest,
  // TODO: give this a better type than Option<String> (everywhere)!
  cache_key_gen_version: Option<String>,
}

impl CacheableExecuteProcessRequest {
  fn new(req: ExecuteProcessRequest, cache_key_gen_version: Option<String>) -> Self {
    CacheableExecuteProcessRequest {
      req,
      cache_key_gen_version,
    }
  }
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

impl FallibleExecuteProcessResult {
  fn without_execution_attempts(&self) -> CacheableExecuteProcessResult {
    CacheableExecuteProcessResult {
      stdout: self.stdout.clone(),
      stderr: self.stderr.clone(),
      exit_code: self.exit_code,
      output_directory: self.output_directory,
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
  fn with_execution_attempts(
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

// TODO: remove this method!
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
        Some(cached_execution_result) => future::result(Ok(cached_execution_result)).to_boxed(),
        // We have to actually run the process now.
        None => inner
          .run(req)
          .and_then(move |res| {
            let cacheable_process_result = res.without_execution_attempts();
            cache
              .record_process_result(cacheable_request, cacheable_process_result.clone())
              .map(|()| cacheable_process_result)
          })
          .to_boxed(),
      })
      // NB: We clear metadata about execution attempts when returning a cacheable process execution
      // request.
      .map(|cacheable_process_result| cacheable_process_result.with_execution_attempts(vec![]))
      .to_boxed()
  }
}
