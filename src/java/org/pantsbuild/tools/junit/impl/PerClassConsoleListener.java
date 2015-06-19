// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.PrintStream;

import org.junit.runner.Description;
import org.junit.runner.Result;

/**
 * A run listener that shows progress and timing for each test class.
 */
class PerClassConsoleListener extends ConsoleListener {
  private final PrintStream out;

  PerClassConsoleListener(PrintStream out) {
    super(out);
    this.out = out;
  }

  @Override
  public void testRunStarted(Description description) throws Exception {
    out.print(description.getDisplayName() + ":");
  }

  @Override
  public void testRunFinished(Result result) {
    out.println(" [" + result.getRunTime() + " ms]");
    super.printFailures(result);
  }

}
