// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.parallel;

import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;
import org.pantsbuild.junit.annotations.TestSerial;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * This test is designed to exercise the TestSerial annotation when run under pants.
 * A similar test runs in tests/java/... to exercise junit-runner standalone.
 * <p>
 * These tests are intended to show that the two classes will be run serially, even if
 * parallel test running is on.
 * To properly exercise this function, both test classes must be running at the same time with
 * the flags:
 * <pre>
 *  --test-junit-default-concurrency=PARALLEL --test-junit-parallel-threads 2
 * <pre>
 * when running with just these two classes as specs.
 * <p>
 * Uses a timeout, so its not completely deterministic, but it gives 3 seconds to allow any
 * concurrency to take place.
 */
@TestSerial
public class AnnotatedSerialTest1 {
  private static final int WAIT_TIMEOUT_MS = 1000;
  private static AtomicBoolean waiting = new AtomicBoolean(false);

  @Test
  public void astest1() throws Exception {
    awaitLatch("astest1");
  }

  static void awaitLatch(String methodName) throws Exception {
    System.out.println("start " + methodName);
    assertFalse(waiting.getAndSet(true));
    Thread.sleep(WAIT_TIMEOUT_MS);
    assertTrue(waiting.getAndSet(false));
    System.out.println("end " + methodName);
  }
}
