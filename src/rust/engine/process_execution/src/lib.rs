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
  /// execution.
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

  fn reset_prefork(&self);
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

  fn reset_prefork(&self) {
    self.inner.reset_prefork();
  }
}
