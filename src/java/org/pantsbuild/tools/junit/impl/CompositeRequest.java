// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.List;

import org.junit.internal.AssumptionViolatedException;
import org.junit.internal.runners.ErrorReportingRunner;
import org.junit.internal.runners.model.EachTestNotifier;
import org.junit.runner.Description;
import org.junit.runner.Request;
import org.junit.runner.Runner;
import org.junit.runner.notification.RunNotifier;
import org.junit.runner.notification.StoppedByUserException;
import org.junit.runners.ParentRunner;
import org.junit.runners.model.InitializationError;

/**
 * A JUnit {@link Request} that is composed of a list of {@link Request}s.
 */
public class CompositeRequest extends ParentRunner<Request> {

  private final List<Request> requests;

  /**
   * Constructor
   * @param requests List of requests to be composed of.
   * @throws InitializationError
   */
  public CompositeRequest(List<Request> requests) throws InitializationError {
    // Note: this works for now, Suite constructor also calls super(null), but it may break some
    // point in future, in which case fall back to implementing Runner may be necessary.
    super(null);
    this.requests = requests;
  }

  @Override
  protected List<Request> getChildren() {
    return requests;
  }

  @Override
  protected Description describeChild(Request child) {
    return child.getRunner().getDescription();
  }

  @Override
  protected void runChild(Request child, RunNotifier notifier) {
    // This mirrors the implementation of ParentRunner.run
    EachTestNotifier eachNotifier = new EachTestNotifier(notifier, describeChild(child));
    try {
      Runner runner = child.getRunner();
      boolean exemptThisRunner = false;
      if (runner instanceof ErrorReportingRunner) {
        // Test sharding may result in no tests running within this request. In that case,
        // FilterRequest.getRunner() returns an instance of ErrorReportingRunner with the
        // Exception instance with known message.
        ErrorReportingRunner erRunner = (ErrorReportingRunner) runner;
        Description desc = erRunner.getDescription();
        if ("org.junit.runner.manipulation.Filter".equals(desc.getDisplayName())) {
          exemptThisRunner = true;
        }
      }
      if (!exemptThisRunner) {
        runner.run(notifier);
      }
    } catch (AssumptionViolatedException e) {
      eachNotifier.fireTestIgnored();
    } catch (StoppedByUserException e) {
      throw e;
    // We wan't to fail the test no matter what here for an intelligible user message.
    // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    } catch (Throwable e) {
      eachNotifier.addFailure(e);
    }
  }

}
