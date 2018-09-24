// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(len_without_is_empty, redundant_field_names)
)]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

extern crate async_semaphore;
extern crate bazel_protos;
#[macro_use]
extern crate boxfuture;
extern crate bytes;
extern crate digest;
extern crate fs;
extern crate futures;
extern crate futures_timer;
extern crate grpcio;
extern crate hashing;
#[macro_use]
extern crate log;
#[cfg(test)]
extern crate mock;
extern crate protobuf;
extern crate resettable;
extern crate sha2;
#[cfg(test)]
extern crate tempfile;
#[cfg(test)]
extern crate testutil;
extern crate tokio_codec;
extern crate tokio_process;

use boxfuture::BoxFuture;
use bytes::Bytes;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::Arc;

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
}

pub trait CommandRunner: Send + Sync {
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String>;

  ///
  /// NB: Unlike other `with_shutdown` methods in the codebase, this method takes a Fn reference,
  /// because in order to be "object safe", `CommandRunner` must not have functions with generic
  /// parameters.
  ///
  fn with_shutdown(&self, f: &mut FnMut() -> ());
}

///
/// A CommandRunner wrapper that limits the number of concurrent requests.
///
pub struct BoundedCommandRunner {
  inner: Arc<Box<CommandRunner>>,
  sema: AsyncSemaphore,
}

impl BoundedCommandRunner {
  pub fn new(inner: Box<CommandRunner>, bound: usize) -> BoundedCommandRunner {
    BoundedCommandRunner {
      inner: Arc::new(inner),
      sema: AsyncSemaphore::new(bound),
    }
  }
}

impl CommandRunner for BoundedCommandRunner {
  fn run(&self, req: ExecuteProcessRequest) -> BoxFuture<FallibleExecuteProcessResult, String> {
    let inner = self.inner.clone();
    self.sema.with_acquired(move || inner.run(req))
  }

  fn with_shutdown(&self, f: &mut FnMut() -> ()) {
    self.inner.with_shutdown(f);
  }
}
