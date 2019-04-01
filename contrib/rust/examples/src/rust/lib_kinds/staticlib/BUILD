# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


cargo_library(
  name='staticlib',
  sources=rglobs('*.rs', 'Cargo.toml', exclude=[rglobs('**/target/*.rs')]),
)
