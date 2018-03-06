// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java org.pantsbuild.contrib.thrifty.common

include "org/pantsbuild/contrib/thrifty/common/common.thrift"

struct ClientLog {
  1: common.Common common;
  2: string message;
}
