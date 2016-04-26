// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Preconditions;
import com.google.common.base.Throwables;
import com.google.common.util.concurrent.ThreadFactoryBuilder;
import java.util.LinkedList;
import java.util.Queue;
import java.util.concurrent.CompletionService;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorCompletionService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ThreadFactory;
import org.junit.runners.model.RunnerScheduler;
import org.pantsbuild.junit.annotations.TestParallel;
import org.pantsbuild.junit.annotations.TestSerial;

public class ConcurrentRunnerScheduler implements RunnerScheduler {
  private final CompletionService<Void> completionService;
  private final Queue<Future<Void>> concurrentTasks;
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
    completionService = new ExecutorCompletionService<Void>(
        Executors.newFixedThreadPool(numThreads, threadFactory));
    concurrentTasks = new LinkedList<Future<Void>>();
    serialTasks = new LinkedList<Runnable>();
  }

  @Override
  public void schedule(Runnable childStatement) {
    if (shouldMethodsRunParallel()) {
      concurrentTasks.offer(completionService.submit(childStatement, null));
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
      concurrentTasks.offer(completionService.submit(childStatement, null));
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
    try {
      // Wait for all concurrent tasks to finish.
      while (!concurrentTasks.isEmpty()) {
        concurrentTasks.poll().get();
      }
      // Then run all serial tasks in serial.
      for (Runnable task : serialTasks) {
        task.run();
      }
    } catch (InterruptedException e) {
      throw new RuntimeException(e);
    } catch (ExecutionException e) {
      // This should not normally happen since junit statements trap and record errors and failures.
      throw Throwables.propagate(e.getCause());
    } finally {
      // In case of error, cancel all in-flight concurrent tasks
      while (!concurrentTasks.isEmpty()) {
        concurrentTasks.poll().cancel(true);
      }
    }
  }
}
