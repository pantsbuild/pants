# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_wire_library(
  sources=[
    # NB: Order matters for these two paths, so we set `ordered_sources=True` below.
    'elements.proto',
    'compound.proto',
  ],
  dependencies=[
    'examples/src/wire/org/pantsbuild/example/temperature',
  ],
  ordered_sources=True,
)
