// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.concurrent.ConcurrentHashMap;
import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/**
 * A listener that keeps track of the current test state with its own result class so it can record
 * the state of tests being run if there is unexpected exit during the tests.
 */
public class ShutdownListener extends RunListener {
  private final Result result = new Result();
  private final RunListener resultListener = result.createListener();
  // holds running tests: Descriptions are added on testStarted and removed on testFinished
  private ConcurrentHashMap.KeySetView<Description, Boolean> currentDescriptions =
    ConcurrentHashMap.newKeySet();
  private RunListener underlying;


  public ShutdownListener(RunListener underlying) {
    this.underlying = underlying;
  }

  public void unexpectedShutdown() {
    for(Description description : currentDescriptions) {
      completeTestWithFailure(description);
    }

    try {
      resultListener.testRunFinished(result);
      underlying.testRunFinished(result);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  private void completeTestWithFailure(Description description) {
    Failure shutdownFailure = new Failure(description,
      new UnknownError("Abnormal VM exit - test crashed. The test run may have timed out."));

    try {
      // Mark this test as completed with a failure (finish its lifecycle)
      resultListener.testFailure(shutdownFailure);
      resultListener.testFinished(description);
      underlying.testFailure(shutdownFailure);
      underlying.testFinished(description);
    } catch (Exception ignored){}
  }

  @Override
  public void testRunStarted(Description description) throws Exception {
    resultListener.testRunStarted(description);
  }

  @Override
  public void testStarted(Description description) throws Exception {
    currentDescriptions.add(description);
    resultListener.testStarted(description);
  }

  @Override
  public void testAssumptionFailure(Failure failure) {
    resultListener.testAssumptionFailure(failure);
  }

  @Override
  public void testRunFinished(Result result) throws Exception {
    resultListener.testRunFinished(result);
  }

  @Override
  public void testFinished(Description description) throws Exception {
    currentDescriptions.remove(description);
    resultListener.testFinished(description);
  }

  @Override
  public void testFailure(Failure failure) throws Exception {
    resultListener.testFailure(failure);
  }

  @Override
  public void testIgnored(Description description) throws Exception {
    resultListener.testIgnored(description);
  }
}
