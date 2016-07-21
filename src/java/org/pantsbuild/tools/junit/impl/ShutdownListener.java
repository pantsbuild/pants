// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.PrintStream;
import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/**
 * A listener that keeps track of the current test state with its own result class so it can print
 * the state of tests being run if there is unexpected exit during the tests.
 */
public class ShutdownListener extends ConsoleListener {
  private final Result result = new Result();
  private final RunListener resultListener = result.createListener();
  private Description currentTestDescription;

  public ShutdownListener(PrintStream out) {
    super(out);
  }

  public void unexpectedShutdown() {
    if (currentTestDescription != null) {
      Failure shutdownFailure = new Failure(currentTestDescription,
          new UnknownError("Abnormal VM exit - test crashed."));
      testFailure(shutdownFailure);
    }

    // Log the test summary to the Console
    super.testRunFinished(result);
  }

  @Override
  public void testRunStarted(Description description) throws Exception {
    this.currentTestDescription = description;
    resultListener.testRunStarted(description);
  }

  @Override
  public void testRunFinished(Result result) {
    try {
      resultListener.testRunFinished(result);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  @Override
  public void testFinished(Description description) throws Exception {
    resultListener.testFinished(description);
  }

  @Override
  public void testFailure(Failure failure) {
    try {
      resultListener.testFailure(failure);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  @Override
  public void testIgnored(Description description) {
    try {
      resultListener.testIgnored(description);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }
}
