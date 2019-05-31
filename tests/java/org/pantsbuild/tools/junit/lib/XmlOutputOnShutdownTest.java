// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 * <p>
 * This test is intended to show that XML test output will be written to disk even when
 * the JUnit process is terminated (usually due to a Pants default test timeout).
 * It registers itself, releases a static lock the caller is awaiting, then blocks itself.
 * This allows the actual test to control this test's progression and make assertions about
 * output written from the test runner.
 * </p>
 */
public class XmlOutputOnShutdownTest {
  private static CountDownLatch never = new CountDownLatch(1);
  public static CountDownLatch testStarted;

  public static void setUpLatch() {
    testStarted = new CountDownLatch(1);
  }

  @Test
  public void hangs() throws InterruptedException {
    TestRegistry.registerTestCall("hangs");
    testStarted.countDown();
    // testXmlOutputOnShutdown interrupts this thread, so ignore that eventuality
    never.await(2, TimeUnit.SECONDS);
  }
}
