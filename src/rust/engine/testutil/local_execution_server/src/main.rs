// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use mock::execution_server::{ExpectedAPICall, MockExecution, MockOperation, TestServer};
use protos::{
    gen::build::bazel::remote::execution::v2::{Digest, ExecuteRequest},
    gen::google::longrunning::Operation,
};
use std::io::Read;

use clap::StructOpt;

#[derive(StructOpt)]
#[structopt(
    name = "local_execution_server",
    about = "A mock execution server, to test remote execution capabilities.\nThe server will handle exactly one request as specified by the optional arguments: request_size and request_digest. In response to this request, it will perform a default operation. It will reject any subsequent request."
)]
struct Options {
    #[structopt(short = 'p', long = "port")]
    port: Option<u16>,
    #[structopt(
        long = "request_hash",
        help = "The hash of the digest from the request the server should expect to receive"
    )]
    request_hash: String,
    #[structopt(
        long = "request_size",
        help = "The size (in bytes) of the digest from the request the server should expect to receive"
    )]
    request_size: i64,
}

fn main() {
    let options = Options::from_args();

    // When the request is executed, perform this operation
    let operation = MockOperation {
        op: Ok(Some(Operation::default())),
        duration: None,
    };

    // The request our server expects to receive
    let request = ExecuteRequest {
        action_digest: Some(Digest {
            hash: options.request_hash,
            size_bytes: options.request_size,
        }),
        ..ExecuteRequest::default()
    };

    let execution = MockExecution::new(vec![ExpectedAPICall::Execute {
        execute_request: request,
        stream_responses: Ok(vec![operation]),
    }]);

    // Start the server
    let server = TestServer::new(execution, options.port);
    println!("Started execution server at address: {}", server.address());

    // Wait for the user to kill us
    println!("Press enter to exit.");
    let mut stdin = std::io::stdin();
    let _ = stdin.read(&mut [0_u8]).unwrap();
}
