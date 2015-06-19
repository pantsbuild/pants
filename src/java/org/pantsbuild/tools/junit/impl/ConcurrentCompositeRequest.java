// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.List;

import org.junit.runner.Request;
import org.junit.runner.notification.RunNotifier;
import org.junit.runners.model.InitializationError;
import org.junit.runners.model.Statement;

/**
 * A Runner for running composite requests in a concurrent fashion.
 */
public class ConcurrentCompositeRequest extends CompositeRequest {

  private final ConcurrentRunnerScheduler runnerScheduler;

  public ConcurrentCompositeRequest(List<Request> requests, boolean defaultParallel, int numThreads)
      throws InitializationError {
    super(requests);
    this.runnerScheduler = new ConcurrentRunnerScheduler(defaultParallel, numThreads);
    setScheduler(runnerScheduler);
  }

  @Override
  protected Statement childrenInvoker(final RunNotifier notifier) {
    return new Statement() {
      @Override
      public void evaluate() {
        for (final Request child : getChildren()) {
          Runnable runnable = new Runnable() {
            @Override
            public void run() {
              runChild(child, notifier);
            }
          };
          if (child instanceof AnnotatedClassRequest) {
            runnerScheduler.schedule(runnable, ((AnnotatedClassRequest) child).getClazz());
          } else {
            runnerScheduler.schedule(runnable);
          }
        }
        runnerScheduler.finished();
      }
    };
  }
}
