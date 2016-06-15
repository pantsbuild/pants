# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_wire_library(name='temperature',
  sources=['temperatures.proto',],

  # For service stub generation:
  # - wire 1.x, the compiler expects the service_writer interface.
  # - wire 2.x, the compiler expects the service_factory interface.
  # To switch between versions of wire you will also need to edit the
  # //:wire-compiler and //:wire-runtime targets in BUILD.tools
  service_writer='com.squareup.wire.SimpleServiceWriter',
)
