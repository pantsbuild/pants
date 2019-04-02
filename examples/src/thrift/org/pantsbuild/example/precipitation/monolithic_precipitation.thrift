// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// "Monolithic" precipitation refers to this target depending on "unexported" distance, which
// doesn't have its own provides=setup_py(), so its sources are copied into the result for this
// target.

namespace java org.pantsbuild.example.precipitation.thriftjava
namespace py org.pantsbuild.example.monolithic_precipitation

include "org/pantsbuild/example/distance/unexported_distance.thrift"

/**
 * Structure for recording weather events, e.g., 8mm of rain.
 */
struct Precipitation {
  1: optional string substance = "rain";
  2: optional unexported_distance.Distance distance;
}
