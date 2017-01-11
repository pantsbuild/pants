// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl.experimental;

import com.google.common.base.Preconditions;
import com.google.common.base.Throwables;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.runner.Computer;
import org.junit.runner.Runner;
import org.junit.runners.ParentRunner;
import org.junit.runners.model.InitializationError;
import org.junit.runners.model.RunnerBuilder;
import org.junit.runners.model.RunnerScheduler;
import org.pantsbuild.tools.junit.impl.Concurrency;

/**
 * This class allows test classes to run in parallel, test methods to run in parallel, or both.
 * <P>
 * NB(zundel): This class implements the JUnitRunner Computer interface which is marked
 * experimental in JUnit itself.  Unfortunately, to use this interface you must pass an entire
 * class into the runner, its not compatible with the Request style of running tests.
 * </P>
 */
public class ConcurrentComputer extends Computer {
  private final Concurrency concurrency;
  private final int numParallelThreads;

  public ConcurrentComputer(Concurrency concurrency, int numParallelThreads) {
    Preconditions.checkNotNull(concurrency);
    this.concurrency = concurrency;
    this.numParallelThreads = numParallelThreads > 0 ? numParallelThreads : 1;
  }

  private Runner parallelize(Runner runner) {
    if (runner instanceof ParentRunner) {
      ((ParentRunner<?>) runner).setScheduler(new RunnerScheduler() {
        private final Map<Future<?>, Runnable> testResults =
            new HashMap<Future<?>, Runnable>();
        private final ExecutorService fService = Executors.newFixedThreadPool(numParallelThreads);

        @Override
        public void schedule(Runnable childStatement) {
          testResults.put(fService.submit(childStatement), childStatement);
        }

        @Override
        public void finished() {
          try {
            fService.shutdown();
            // TODO(zundel): Change long wait?
            boolean awaitResult = fService.awaitTermination(Long.MAX_VALUE, TimeUnit.NANOSECONDS);
            if (awaitResult != true) {
              throw new ConcurrentTestRunnerException("Did not terminate all tests sucessfully.");
            }
            for (Future<?> testResult : testResults.keySet()) {
              if (testResult.isDone()) {
                try {
                  testResult.get();
                } catch (ExecutionException e) {
                  Throwables.propagate(e);
                }
              } else if (testResult.isCancelled()) {
                throw new ConcurrentTestRunnerException("Some tests did not run (cancelled)");
              } else {
                throw new ConcurrentTestRunnerException("Some tests did not run.");
              }
            }
          } catch (InterruptedException e) {
            e.printStackTrace(System.err);
          }
        }
      });
    }
    return runner;
  }

  @Override
  public Runner getSuite(RunnerBuilder builder, java.lang.Class<?>[] classes)
      throws InitializationError {
    Runner suite = super.getSuite(builder, classes);
    return this.concurrency.shouldRunClassesParallel() ? parallelize(suite) : suite;
  }

  @Override
  protected Runner getRunner(RunnerBuilder builder, Class<?> testClass)
      throws Throwable {
    Runner runner = super.getRunner(builder, testClass);
    return this.concurrency.shouldRunMethodsParallel() ? parallelize(runner) : runner;
  }
}
