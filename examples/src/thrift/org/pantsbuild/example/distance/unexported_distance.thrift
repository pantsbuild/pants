// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// "Unexported" distance merely refers to the BUILD file for this target not setting a
// provides=setup_py().

namespace java org.pantsbuild.example.distance.thriftjava
namespace py org.pantsbuild.example.unexported_distance

/**
 * Structure for expressing distance measures: 8mm, 12 parsecs, etc.
 * Not so useful on its own.
 */
struct Distance {
  1: optional string Unit;
  2: required i64 Number;
}
