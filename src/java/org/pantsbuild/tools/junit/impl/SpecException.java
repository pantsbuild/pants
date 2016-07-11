// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

class SpecException extends Exception {

  public SpecException(String spec, String message) {
    super(formatMessage(spec, message));
  }

  public SpecException(String spec, String message, Throwable t) {
    super(formatMessage(spec, message), t);
  }

  private static String formatMessage(String spec, String message) {
    return String.format("FATAL: Error parsing spec '%s': %s",spec, message);
  }
}
