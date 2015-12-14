// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.PrintStream;

import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/**
 * A console listener that shows description of each test class.
 */
class PerTestConsoleListener extends ConsoleListener {
  private final PrintStream out;

  PerTestConsoleListener(PrintStream out) {
    super(out);
    this.out = out;
  }

  @Override
  public void testRunStarted(Description description) throws Exception {
    String displayName = Util.getPantsFriendlyDisplayName(description);
    if (displayName != "null") {
      out.println(displayName);
    }
  }

  @Override
  public void testStarted(Description description) {
    out.print("\t" + Util.getPantsFriendlyDisplayName(description));
  }

  @Override
  public void testFinished(Description description) throws Exception {
    out.println();
  }

  @Override
  public void testFailure(Failure failure) {
    out.println(" -> FAILED");
  }

}
