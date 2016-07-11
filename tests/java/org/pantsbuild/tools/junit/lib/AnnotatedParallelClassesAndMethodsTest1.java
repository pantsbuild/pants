// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.pantsbuild.junit.annotations.TestParallelClassesAndMethods;

import static org.junit.Assert.assertTrue;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 * <p>
 * Exercises the TestParallelClassesAndMethods annotation.
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
@TestParallelClassesAndMethods
public class AnnotatedParallelClassesAndMethodsTest1 {
  private static final int NUM_CONCURRENT_TESTS = 4;
  private static final int WAIT_TIMEOUT_MS = 3000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);

  public static void reset() {
    latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
  }

  @Test
  public void apmcatest11() throws Exception {
    awaitLatch("apcamtest11");
  }

  @Test
  public void apmcatest12() throws Exception {
    awaitLatch("apcamtest12");
  }
    static void awaitLatch(String methodName) throws Exception {
      TestRegistry.registerTestCall(methodName);
      latch.countDown();
      assertTrue(latch.await(WAIT_TIMEOUT_MS, TimeUnit.MILLISECONDS));
    }
}
