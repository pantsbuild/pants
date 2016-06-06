// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.parallelmethods;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * This test is designed to exercise the test.junit task argument:
 * --test-junit-default-concurrency=PARALLEL_METHODS
 * <P>
 * There is a similar test under tests/java/ to test the junit-runner standalone.
 * <p>
 * For all methods in ParallelMethodsDefaultParallelTest1 and ParallelMethodsDefaultParallelTest2
 * to succeed all of the test methods in each class must be running at the same time. But both
 * classes should not run in parallel.  Intended to test the flags:
 * <pre>
 * --test-junit-default-concurrency=PARALLEL_METHODS --test-junit-parallel-threads=4
 * <pre>
 * when running with just these two classes as specs.
 * <p>
 * Runs in on the order of 10 milliseconds locally, but it may take longer on a CI machine to spin
 * up 4 threads, so it has a generous timeout set.
 */
public class ParallelMethodsDefaultParallelTest1 {
  private static final int NUM_CONCURRENT_TESTS = 2;
  private static final int WAIT_TIMEOUT_MS = 1000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
  private static AtomicInteger numRunning = new AtomicInteger(0);

  @Test
  public void pmdptest11() throws Exception {
    awaitLatch("pmdptest11");
  }

  @Test
  public void pmdptest12() throws Exception {
    awaitLatch("pmdptest12");
  }

  static void awaitLatch(String methodName) throws Exception {
    // NB(zundel): this test currently doesn't ensure that both classes run all methods in
    // parallel, it only es that at least two methods get started and that no more than
    // 2 methods run at a time. A better test would show that methods are run in parallel
    // in each class.

    System.out.println("start " + methodName);
    latch.countDown();
    // Make sure that we wait for at least 2 methods to get started to ensure there is some
    // parallelism going on.
    assertTrue(latch.await(WAIT_TIMEOUT_MS, TimeUnit.MILLISECONDS));
    numRunning.incrementAndGet();
    Thread.sleep(WAIT_TIMEOUT_MS);
    // Make sure no more than 2 tests have been started concurrently
    assertTrue(numRunning.get() <= NUM_CONCURRENT_TESTS);
    numRunning.decrementAndGet();
    System.out.println("end " + methodName);
  }
}
