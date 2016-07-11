// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 *<p>
 * Exercises the junit runner PARALLEL_CLASSES_AND_METHODS concurrency strategy.
 * <p>
 * For all methods in ParallelClassesAndMethodsDefaultParallelTest1 and
 * ParallelClassesAndMethodsDefaultParallelTest1 to succeed all of the test methods must be
 * running at the same time. Intended to test the flags:
 * <p>
 * -default-concurrence PARALLEL_CLASSES_AND_METHODS -parallel-threads 4
 * <p>
 * when running with just these two classes as specs.
 * <p>
 * Runs in on the order of 10 milliseconds locally, but it may take longer on a CI machine to spin
 * up 4 threads, so it has a generous timeout set.
 * </p>
 */
public class ParallelClassesAndMethodsDefaultParallelTest1 {
  private static final int NUM_CONCURRENT_TESTS = 4;
  private static final int RETRY_TIMEOUT_MS = 3000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);

  public static void reset() {
    latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
  }

  @Test
  public void pbdptest11() throws Exception {
    awaitLatch("pbdptest11");
  }

  @Test
  public void pbdptest12() throws Exception {
    awaitLatch("pbdptest12");
  }

  static void awaitLatch(String methodName) throws Exception {
    TestRegistry.registerTestCall(methodName);
    latch.countDown();
    assertTrue(latch.await(RETRY_TIMEOUT_MS, TimeUnit.MILLISECONDS));
  }
}
