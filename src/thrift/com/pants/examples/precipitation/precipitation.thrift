// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java com.pants.examples.precipitation.thriftjava
namespace py com.pants.examples.precipitation

include "com/pants/examples/distance/distance.thrift"

/**
 * Structure for recording weather events, e.g., 8mm of rain.
 */
struct Precipitation {
  1: optional string substance = "rain";
  2: optional distance.Distance distance;
}