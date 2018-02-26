// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java org.pantsbuild.contrib.thrifty.common

struct Common {
  1: optional i64 timestamp
  2: required string hostname;
}
