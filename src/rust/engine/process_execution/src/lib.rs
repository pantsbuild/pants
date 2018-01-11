extern crate bazel_protos;
extern crate digest;
extern crate grpcio;
#[cfg(test)]
extern crate mock;
extern crate protobuf;
extern crate sha2;
#[cfg(test)]
extern crate testutil;

use std::collections::BTreeMap;

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
}

///
/// The result of running a process.
///
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecuteProcessResult {
  pub stdout: Vec<u8>,
  pub stderr: Vec<u8>,
  pub exit_code: i32,
}
