extern crate bazel_protos;
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
extern crate tempdir;
#[cfg(test)]
extern crate testutil;

use bytes::Bytes;
use std::collections::BTreeMap;
use std::hash::{Hash, Hasher};

pub mod local;
pub mod remote;

///
/// A process to be executed.
///
#[derive(Clone, Debug)]
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

  pub timeout: std::time::Duration,
  pub description: String,
}

impl PartialEq for ExecuteProcessRequest {
  fn eq(&self, other: &ExecuteProcessRequest) -> bool {
    self.argv == other.argv && self.env == other.env && self.input_files == other.input_files
      && self.timeout == other.timeout
  }
}
impl Eq for ExecuteProcessRequest {}

impl Hash for ExecuteProcessRequest {
  fn hash<H: Hasher>(&self, state: &mut H) {
    self.argv.hash(state);
    self.env.hash(state);
    self.input_files.hash(state);
    self.timeout.hash(state);
  }
}

///
/// The result of running a process.
///
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecuteProcessResult {
  pub stdout: Bytes,
  pub stderr: Bytes,
  pub exit_code: i32,
}
