# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


cargo_library(
  name='library',
  sources=rglobs('*.rs', 'Cargo.toml', exclude=[rglobs('**/target/*.rs')]),
  dependencies=[
    'contrib/rust/examples/src/rust/workspace:workspace',
  ]
)
