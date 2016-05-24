// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl.experimental;

public class ConcurrentTestRunnerException extends RuntimeException {
  public ConcurrentTestRunnerException(String message) {
    super(message);
  }
  public ConcurrentTestRunnerException(String message, Throwable t) {
    super(message, t);
  }
}
