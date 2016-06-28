// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 * <p>
 * This test is just like {@link AnnotatedSerialTest1} but without the annotation.
 * Exercises the -default-concurrency SERIAL option
 * <p>
 * These tests are intended to show that the two classes will be run serially, even if
 * parallel test running is on.
 * To properly exercise this function, both test classes must be running at the same time with
 * the option -default-concurrency SERIAL option when running with just these two classes as specs.
 * <p>
 * Uses a timeout, so its not completely deterministic, but it gives 3 seconds to allow any
 * concurrency to take place.
 * </p>
 */
public class SerialTest1 {
  private static final int WAIT_TIMEOUT_MS = 1000;
  private static final AtomicBoolean waiting = new AtomicBoolean(false);

  public static void reset() {
    waiting.set(false);
  }

  @Test
  public void stest1() throws Exception {
    awaitLatch("stest1");
  }

  static void awaitLatch(String methodName) throws Exception {
    TestRegistry.registerTestCall(methodName);
    assertFalse(waiting.getAndSet(true));
    Thread.sleep(WAIT_TIMEOUT_MS);
    assertTrue(waiting.getAndSet(false));
  }
}
