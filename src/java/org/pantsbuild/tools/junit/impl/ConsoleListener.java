// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.PrintStream;

import org.junit.internal.TextListener;
import org.junit.runner.notification.Failure;

/**
 * A run listener that logs test events with single characters.
 */
class ConsoleListener extends TextListener {
  private final PrintStream out;

  ConsoleListener(PrintStream out) {
    super(out);
    this.out = out;
  }

  @Override
  public void testFailure(Failure failure) {
    out.append(Util.isAssertionFailure(failure) ? 'F' : 'E');
  }
}
