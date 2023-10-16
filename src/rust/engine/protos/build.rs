// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use prost_build::Config;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut config = Config::new();
    config.bytes(&["."]);

    tonic_build::configure()
    .build_client(true)
    .build_server(true)
    .compile_with_config(
      config,
      &[
        "protos/bazelbuild_remote-apis/build/bazel/remote/execution/v2/remote_execution.proto",
        "protos/bazelbuild_remote-apis/build/bazel/semver/semver.proto",
        "protos/buildbarn/cas.proto",
        "protos/googleapis/google/bytestream/bytestream.proto",
        "protos/googleapis/google/rpc/code.proto",
        "protos/googleapis/google/rpc/error_details.proto",
        "protos/googleapis/google/rpc/status.proto",
        "protos/googleapis/google/longrunning/operations.proto",
        "protos/pants/cache.proto",
        "protos/standard/google/protobuf/empty.proto",
      ],
      &[
        "protos/bazelbuild_remote-apis",
        "protos/buildbarn",
        "protos/googleapis",
        "protos/pants",
        "protos/standard",
      ],
    )?;

    Ok(())
}
