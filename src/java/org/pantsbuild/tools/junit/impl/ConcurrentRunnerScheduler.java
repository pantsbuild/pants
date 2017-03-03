// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.LinkedList;
import java.util.Queue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;

import com.google.common.base.Preconditions;
import com.google.common.util.concurrent.ThreadFactoryBuilder;

import org.junit.runners.model.RunnerScheduler;
import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestSerial;

public class ConcurrentRunnerScheduler implements RunnerScheduler {
  private final ExecutorService executor;
  private final Queue<Runnable> serialTasks;
  private final Concurrency defaultConcurrency;

  /**
   * A concurrent scheduler to run junit tests in parallel if possible, followed by tests that can
   * only be run in serial.
   *
   * Test classes annotated with {@link TestSerial} will be run in serial.
   * Test classes annotated with {@link TestParallel} will be run in parallel.
   * Test classes without neither annotation will be run in parallel if defaultParallel is set.
   *
   * Call {@link org.junit.runners.ParentRunner#setScheduler} to use this scheduler.
   *
   * @param defaultConcurrency  Describes how to parallelize unannotated classes.
   * @param numThreads Number of parallel threads to use, must be positive.
   */
  public ConcurrentRunnerScheduler(Concurrency defaultConcurrency,
      int numThreads) {
    Preconditions.checkNotNull(defaultConcurrency);
    this.defaultConcurrency = defaultConcurrency;
    ThreadFactory threadFactory = new ThreadFactoryBuilder()
        .setDaemon(true)
        .setNameFormat("concurrent-junit-runner-%d")
        .build();
    executor = Executors.newFixedThreadPool(numThreads, threadFactory);
    serialTasks = new LinkedList<Runnable>();
  }

  @Override
  public void schedule(Runnable childStatement) {
    if (shouldMethodsRunParallel()) {
      executor.execute(childStatement);
    } else {
      serialTasks.offer(childStatement);
    }
  }

  /**
   * Schedule a test childStatement associated with clazz, using clazz's policy to decide running
   * in serial or parallel.
   */
  public void schedule(Runnable childStatement, Class<?> clazz) {
    if (shouldClassRunParallel(clazz)) {
      executor.execute(childStatement);
    } else {
      serialTasks.offer(childStatement);
    }
  }

  private boolean shouldMethodsRunParallel() {
    // TODO(zundel): Add support for an annotation like TestParallelMethods.
    return defaultConcurrency.shouldRunMethodsParallel();
  }

  private boolean shouldClassRunParallel(Class<?> clazz) {
    return !clazz.isAnnotationPresent(TestSerial.class)
        && (clazz.isAnnotationPresent(TestParallel.class) ||
        defaultConcurrency.shouldRunClassesParallel());
  }

  @Override
  public void finished() {
    executor.shutdown();
    try {
      // Wait for all concurrent tasks to finish.
      executor.awaitTermination(Long.MAX_VALUE, TimeUnit.DAYS);

      // Then run all serial tasks in serial.
      for (Runnable task : serialTasks) {
        task.run();
      }
    } catch (InterruptedException e) {
      throw new RuntimeException(e);
    } finally {
      // In case of error, cancel all in-flight concurrent tasks
      executor.shutdownNow();
    }
  }
}
