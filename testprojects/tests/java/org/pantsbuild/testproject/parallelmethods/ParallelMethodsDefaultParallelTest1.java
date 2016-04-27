// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.parallelmethods;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * This test is designed to exercise the test.junit task argument:
 * --test-junit-default-concurrency=PARALLEL_METHODS
 * <P>
 * There is a similar test under tests/java/ to test the junit-runner standalone.
 * <p>
 * For all methods in ParallelMethodsDefaultParallelTest1 and ParallelMethodsDefaultParallelTest2
 * to succeed all of the test methods must be running at the same time. Intended to test the flags:
 * <pre>
 * --test-junit-default-concurrency=PARALLEL_METHODS --test-junit-parallel-threads=4
 * <pre>
 * when running with just these two classes as specs.
 * <p>
 * Runs in on the order of 10 milliseconds locally, but it may take longer on a CI machine to spin
 * up 4 threads, so it has a generous timeout set.
 */
public class ParallelMethodsDefaultParallelTest1 {
  private static final int NUM_CONCURRENT_TESTS = 4;
  private static final int RETRY_TIMEOUT_MS = 3000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);

  @Test
  public void pmdptest11() throws Exception {
    awaitLatch("pmdptest11");
  }

  @Test
  public void pmdptest12() throws Exception {
    awaitLatch("pmdptest12");
  }

  static void awaitLatch(String methodName) throws Exception {
    System.out.println("start " + methodName);
    latch.countDown();
    assertTrue(latch.await(RETRY_TIMEOUT_MS, TimeUnit.MILLISECONDS));
    System.out.println("end " + methodName);
  }
}
