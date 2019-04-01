# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


cargo_library(
  name='lib_d',
  sources=rglobs('*.rs', 'Cargo.toml', exclude=[rglobs('**/target/*.rs')]),
  dependencies=[
    "contrib/rust/examples/src/rust/dependencies/workspace_a:workspace_a",
    "contrib/rust/examples/src/rust/dependencies/workspace_b:workspace_b"
  ]
)
