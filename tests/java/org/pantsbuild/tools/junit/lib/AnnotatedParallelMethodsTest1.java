// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;
import org.pantsbuild.junit.annotations.TestParallelMethods;

import static org.junit.Assert.assertTrue;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 * <p>
 * Exercises the TestParallelMethods annotation.
 * <p>
 * For all methods in AnnotatedParallelMethodsTest1 and AnnotatedParallelMethodsTest2
 * to succeed, both test classes  must be running at the same time with the flag:
 * <pre>
 *  -parallel-threads 2
 * </pre>
 * when running with just these two classes as specs.
 * <p>
 * Runs in on the order of 10 milliseconds locally, but it may take longer on a CI machine to spin
 * up 2 threads, so it has a generous timeout set.
 * </p>
 */
@TestParallelMethods
public class AnnotatedParallelMethodsTest1 {
  private static final int NUM_CONCURRENT_TESTS = 2;
  private static final int WAIT_TIMEOUT_MS = 3000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
  private static final AtomicInteger numRunning = new AtomicInteger(0);

  public static void reset() {
    latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
    numRunning.set(0);
  }

  @Test
  public void apmtest11() throws Exception {
    awaitLatch("apmtest11");
  }

  @Test
  public void apmtest12() throws Exception {
    awaitLatch("apmtest12");
  }

  static void awaitLatch(String methodName) throws Exception {
    // NB(zundel): this test currently doesn't ensure that both classes run all methods in
    // parallel, but the classes run serially, it only ensures that at least two methods get
    // started and that no more than 2 methods run at a time. A better test would show that
    // methods are run in parallel in each class.

    TestRegistry.registerTestCall(methodName);
    latch.countDown();
    // Make sure that we wait for at least 2 methods to get started to ensure there is some
    // parallelism going on.
    assertTrue(latch.await(WAIT_TIMEOUT_MS, TimeUnit.MILLISECONDS));
    numRunning.incrementAndGet();
    Thread.sleep(WAIT_TIMEOUT_MS);
    // Make sure no more than 2 tests have been started concurrently
    int running = numRunning.get();
    assertTrue(String.format("Expected <= %d got %d", NUM_CONCURRENT_TESTS, running),
        running <= NUM_CONCURRENT_TESTS);
    numRunning.decrementAndGet();
  }
}
