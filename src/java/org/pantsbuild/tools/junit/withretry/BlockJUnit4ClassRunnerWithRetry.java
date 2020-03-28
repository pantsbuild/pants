// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.withretry;

import java.io.PrintStream;
import java.util.ArrayList;
import java.util.List;

import org.junit.runner.Description;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunNotifier;
import org.junit.runners.BlockJUnit4ClassRunner;
import org.junit.runners.model.FrameworkMethod;
import org.junit.runners.model.InitializationError;
import org.junit.runners.model.Statement;

/**
 * A subclass of BlockJUnit4ClassRunner that supports retrying failing tests, up to the
 * specified number of attempts. This is useful if some tests are known or suspected
 * to be flaky.
 */
public class BlockJUnit4ClassRunnerWithRetry extends BlockJUnit4ClassRunner {

  private final int numRetries;
  private final PrintStream err;

  public BlockJUnit4ClassRunnerWithRetry(Class<?> klass, int numRetries, PrintStream err)
      throws InitializationError {
    super(klass);
    this.numRetries = numRetries;
    this.err = err;
  }

  @Override
  protected void runChild(final FrameworkMethod method, RunNotifier notifier) {
    Description description = describeChild(method);
    if (isIgnored(method)) {
      notifier.fireTestIgnored(description);
    } else {
      if (numRetries == 0) {
        runLeaf(methodBlock(method), description, notifier);
      } else {
        List<Throwable> errors = new ArrayList<>();
        Description retryDescription;
        FailureCollectingStatement st;
        for (int i = 0; i <= numRetries; i++) {
          st = new FailureCollectingStatement(methodBlock(method));
          retryDescription = descriptionForRetry(method, i);
          runLeaf(st, retryDescription, notifier);
          if (st.error == null) {
            if (i > 0) {
              err.println(
                  "Test " + describeChild(method) + " is FLAKY; passed after " + (i + 1) +
                      " attempts");
            }
            return;
          } else {
            errors.add(st.error);
          }
        }

        // fire errors for each retry, or fire one error for the last one
        int i = 0;
        for (Throwable error : errors) {
          notifier.fireTestFailure(new Failure(descriptionForRetry(method, i), error));
          i++;
        }
      }
    }
  }

  private Description descriptionForRetry(FrameworkMethod method, int i) {
    Description description = describeChild(method);
    if (i == 0) {
      return description;
    }
    return Description.createTestDescription(description.getClassName(),
        description.getMethodName() + " retry (" + i + "/" + numRetries + ")");
  }

  private static class FailureCollectingStatement extends Statement {
    private final Statement statement;
    private Throwable error;

    public FailureCollectingStatement(Statement statement) {
      this.statement = statement;
    }

    @Override public void evaluate() throws Throwable {
      try {

        statement.evaluate();

        return;
        // We want implement generic retry logic here with exception capturing as a key part.
        // SUPPRESS CHECKSTYLE RegexpSinglelineJava
      } catch (Throwable t) {
        // Test failed - save the very first thrown exception. However, if we caught an
        // Error other than AssertionError, exit immediately. It probably doesn't make
        // sense to retry a test after an OOM or LinkageError.
        if (t instanceof Exception || t instanceof AssertionError) {
          error = t;
        } else {
          throw t;
        }
      }
    }
  }
}
