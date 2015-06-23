// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit;

import java.io.PrintStream;

import org.junit.runner.Description;
import org.junit.runner.notification.Failure;

/**
 * A run listener that shows progress and timing for each test class.
 */
class PerTestConsoleListener extends ConsoleListener {
  private final PrintStream out;

  PerTestConsoleListener(PrintStream out) {
    super(out);
    this.out = out;
  }

  @Override
  public void testStarted(Description description) {
    out.print(description.getDisplayName());
  }

  @Override
  public void testFinished(Description description) throws Exception {
    out.println();
  }

  @Override
  public void testFailure(Failure failure) {
    out.println("FAILED");
  }

}
