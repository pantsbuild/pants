// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

fn main() -> Result<(), Box<dyn std::error::Error>> {
  tonic_build::configure()
    .build_client(true)
    .build_server(true)
    .compile(
      &[
        "protos/bazelbuild_remote-apis/build/bazel/remote/execution/v2/remote_execution.proto",
        "protos/bazelbuild_remote-apis/build/bazel/semver/semver.proto",
        "protos/googleapis/google/bytestream/bytestream.proto",
        "protos/googleapis/google/rpc/code.proto",
        "protos/googleapis/google/rpc/error_details.proto",
        "protos/googleapis/google/rpc/status.proto",
        "protos/googleapis/google/longrunning/operations.proto",
        "protos/standard/google/protobuf/empty.proto",
      ],
      &[
        "protos/bazelbuild_remote-apis",
        "protos/googleapis",
        "protos/standard",
      ],
    )?;

  Ok(())
}
