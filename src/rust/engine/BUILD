# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Track files depended on to build the native engine to allow for downstream invalidations.
files(
  sources=["**/Cargo.*", "**/*.rs", "!**/target/*", "!process_execution/bazel_protos"],
  dependencies=[
    'src/rust/engine/process_execution/bazel_protos'
  ]
)
