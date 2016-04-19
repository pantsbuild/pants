package org.pantsbuild.tools.junit.lib;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 *
 * This test is designed to exercise the junit runner -parallel-methods argument
 * <p>
 * For all methods in ParallelMethodsDefaultParallelTest1 and ParallelMethodsDefaultParallelTest2
 * to succeed all of the test methods must be running at the same time. Intended to test the flags
 * <p>
 * -parallel-methods -default-parallel -parallel-threads 4
 * <p>
 * when running with just these two classes as specs.
 * <p>
 * Runs in on the order of 10 milliseconds locally, but it may take longer on a CI machine to spin
 * up 4 threads, so it has a generous timeout set.
 * </p>
 */
public class ParallelMethodsDefaultParallelTest1 {
  private static final int NUM_CONCURRENT_TESTS = 4;
  private static final int RETRY_TIMEOUT_MS = 10000;
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
    TestRegistry.registerTestCall(methodName);
    System.out.println("start " + methodName);
    latch.countDown();
    assertTrue(latch.await(RETRY_TIMEOUT_MS, TimeUnit.MILLISECONDS));
    System.out.println("end " + methodName);
  }
}
