// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java org.pantsbuild.example.precipitation.thriftjava
namespace py org.pantsbuild.example.precipitation

include "org/pantsbuild/example/distance/distance.thrift"

/**
 * Structure for recording weather events, e.g., 8mm of rain.
 */
struct Precipitation {
  1: optional string substance = "rain";
  2: optional distance.Distance distance;
}
