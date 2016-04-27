// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.parallel;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * This test is designed to exercise the test.junit runner --test-junit-default-parallel argument
 * There is a similar test under tests/java/src/... to thest junit-runner standalone.
 * <p>
 * For all methods in ParallelTest1 and ParallelTest2
 * to succeed, both test classes  must be running at the same time. Intended to test the flags
 * <pre>
 * --test-junit-default-concurrency=PARALLEL --test-junit-parallel-threads=2
 * <pre>
 * when running with just these two classes as specs.
 * <p>
 * Runs in on the order of 10 milliseconds locally, but it may take longer on a CI machine to spin
 * up 2 threads, so it has a generous timeout set.
 */
public class ParallelTest1 {
  private static final int NUM_CONCURRENT_TESTS = 2;
  private static final int RETRY_TIMEOUT_MS = 3000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);

  @Test
  public void ptest1() throws Exception {
    awaitLatch("ptest11");
  }

  static void awaitLatch(String methodName) throws Exception {
    System.out.println("start " + methodName);
    latch.countDown();
    assertTrue(latch.await(RETRY_TIMEOUT_MS, TimeUnit.MILLISECONDS));
    System.out.println("end " + methodName);
  }
}
