// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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

use bazel_protos::{
  operations::Operation,
  remote_execution::{Digest, OutputFile},
};
use mock::execution_server::{MockExecution, MockOperation, TestServer};
use protobuf::{self, Message};
use std::io::Read;
use structopt::StructOpt;

#[derive(StructOpt)]
#[structopt(
  name = "local_execution_server",
  about = "A mock execution server, to test remote execution capabilities.\nThe server will handle exactly one request as specified by the optional arguments: request_size and request_digest. In response to this request, it will perform a default operation. It will reject any subsequent request."
)]
struct Options {
  #[structopt(short = "p", long = "port")]
  port: Option<u16>,
  #[structopt(
    long = "output_paths",
    help = "The paths that the client expects to be returned in the ExecuteResponse."
  )]
  output_paths: Vec<String>,
}

/// The digest of an empty string
/// It has the interesting property that the CAS server will always have it even without having to
/// upload anything, which can make up for the absence of actual work being done and uploading
/// actual files to it in a test configuration
fn empty_digest() -> Digest {
  let mut digest = Digest::new();
  digest.set_hash("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855".into());
  digest
}

/// Generate the protobuf types for a list of empty files at these paths.
fn output_files(paths: &[String]) -> protobuf::RepeatedField<OutputFile> {
  protobuf::RepeatedField::from_vec(
    paths
      .iter()
      .map(|path| {
        let mut output_file = OutputFile::new();
        output_file.set_path(path.into());
        output_file.set_digest(empty_digest());
        output_file
      })
      .collect(),
  )
}

/// Generate a dumb operation that exits with 0 (success) and contains empty files for all the
/// output_paths requested.
fn mock_operation(output_paths: &[String]) -> MockOperation {
  let mut op = Operation::new();
  op.set_name(String::new());
  op.set_done(true);
  let mut exec_response = bazel_protos::remote_execution::ExecuteResponse::new();
  exec_response.set_result({
    let mut action_result = bazel_protos::remote_execution::ActionResult::new();
    action_result.set_output_files(output_files(output_paths));
    action_result.set_exit_code(0);
    action_result
  });
  let mut response = protobuf::well_known_types::Any::new();
  response.set_type_url(
    "type.googleapis.com/build.bazel.remote.execution.v2.ExecuteResponse".to_string(),
  );
  let response_bytes = exec_response.write_to_bytes().unwrap();
  response.set_value(response_bytes);
  op.set_response(response);

  MockOperation {
    op: Ok(Some(op)),
    duration: None,
  }
}

fn main() {
  let options = Options::from_args();

  // When the request is executed, perform this operation.
  // If any more request is sent, the server will fail.
  let operations = vec![mock_operation(&options.output_paths)];
  // We will accept any request
  let request = None;
  let execution = MockExecution::new("Mock execution".to_string(), request, operations);

  // Start the server
  let server = TestServer::new(execution, options.port);
  println!("Started execution server at address: {}", server.address());

  // Wait for the user to kill us
  println!("Press enter to exit.");
  let mut stdin = std::io::stdin();
  let _ = stdin.read(&mut [0_u8]).unwrap();
}
