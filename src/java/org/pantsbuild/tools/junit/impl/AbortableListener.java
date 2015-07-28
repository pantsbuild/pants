// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.runner.Description;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/**
 * A listener that can be manually aborted while still retaining normal test suite finishing
 * behavior for its underlying listeners.
 */
abstract class AbortableListener extends ForwardingListener {
  private final Result result = new Result();
  private final boolean failFast;
  private Description started;

  /**
   * Creates a new abortable listener that optionally fails a test run on its first failure.
   *
   * @param failFast Pass {@code true} to {@link #abort(Result)} a test suite on its first failure.
   */
  AbortableListener(boolean failFast) {
    this.failFast = failFast;
    addListener(result.createListener());
  }

  @Override
  public void testStarted(Description description) throws Exception {
    this.started = description;
    super.testStarted(description);
  }

  @Override
  public void testFailure(Failure failure) throws Exception {
    // Allow any listeners to handle the failure in the normal way first.
    super.testFailure(failure);

    if (failFast) {
      finish();

      // Allow the subclass to actually stop the test run.
      abort(result);
    }
  }

  /**
   * Signals a test run is aborting and and passes this signal to underlying listeners with a
   * simulated test suite finishing cycle.
   *
   * @param reason The reason the test run is being stopped.
   * @throws Exception If the underlying listener throws.
   */
  void abort(Throwable reason) throws Exception {
    if (started != null) {
      super.testFailure(new Failure(started, reason));
    }
    finish();
  }

  private void finish() throws Exception {
    // Simulate the junit test run lifecycle end.
    testRunFinished(result);
  }

  /**
   * Called on the first test failure.  Its expected that subclasses will halt the test run in some
   * way.
   *
   * @param failureResult The test result for the failing suite up to and including the first
   *     failure
   */
  protected abstract void abort(Result failureResult);
}
