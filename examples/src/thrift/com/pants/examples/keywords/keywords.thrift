// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java com.pants.examples.keywords.another.thriftjava
namespace py com.pants.examples.keywords.keywords

include "another.thrift"

/**
 * Structure with field names consisting of python keywords.
 */
struct Keywords {
  1: optional string from;
  2: required i64 None;
  3: required another.Another another;
}
