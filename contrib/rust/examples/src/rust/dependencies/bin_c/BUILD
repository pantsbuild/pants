# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


cargo_binary(
  name='bin_c',
  sources=rglobs('*.rs', 'Cargo.toml', exclude=[rglobs('**/target/*.rs')]),
  dependencies=[
      "contrib/rust/examples/src/rust/dependencies/lib_d:lib_d"
  ]
)
