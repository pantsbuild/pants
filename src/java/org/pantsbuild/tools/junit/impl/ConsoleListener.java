// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.PrintStream;

import org.junit.internal.TextListener;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/**
 * A run listener that logs test events with single characters.
 */
class ConsoleListener extends TextListener {
  private final PrintStream out;
  private boolean testsFinished;

  ConsoleListener(PrintStream out) {
    super(out);
    this.out = out;
    testsFinished = false;
  }

  @Override public void testRunFinished(Result result) {
    super.testRunFinished(result);
    testsFinished = true;
  }

  @Override
  public void testFailure(Failure failure) {
    if (testsFinished) {
      // If this method is called after the testRunFinished callback then it means another listener
      // threw an exception in its testRunFinished callback. This is our chance to display the error
      failure.getException().printStackTrace(out);
    } else {
      out.append(Util.isAssertionFailure(failure) ? 'F' : 'E');
    }
  }
}
