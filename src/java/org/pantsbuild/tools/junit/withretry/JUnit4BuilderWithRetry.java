// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.withretry;

import java.io.PrintStream;

import org.junit.internal.builders.JUnit4Builder;
import org.junit.runner.Runner;

/**
 * Needed to support retrying flaky tests. Using method overriding, gives us access to code
 * in JUnit4 that cannot be customized in a simpler way.
 */
public class JUnit4BuilderWithRetry extends JUnit4Builder {

  private final int numRetries;
  private final PrintStream err;

  public JUnit4BuilderWithRetry(int numRetries, PrintStream err) {
    this.numRetries = numRetries;
    this.err = err;
  }

  @Override
  public Runner runnerForClass(Class<?> testClass) throws Throwable {
    return new BlockJUnit4ClassRunnerWithRetry(testClass, numRetries, err);
  }

}
