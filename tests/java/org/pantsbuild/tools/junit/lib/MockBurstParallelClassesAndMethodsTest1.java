// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import com.squareup.burst.BurstJUnit4;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;

import static org.junit.Assert.assertTrue;

@RunWith(BurstJUnit4.class)
public class MockBurstParallelClassesAndMethodsTest1 {
  private static final int NUM_CONCURRENT_TESTS = 5;
  private static final int RETRY_TIMEOUT_MS = 3000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);

  private final ColorType colorType;
  public enum ColorType {
    RED, BLUE
  }

  public static void reset() {
    latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
  }

  public MockBurstParallelClassesAndMethodsTest1(ColorType colorType) {
    this.colorType = colorType;
  }

  @Test
  public void bpcamtest1() throws Exception {
    awaitLatch("bpcamtest1:" + colorType.name());
  }

  static void awaitLatch(String methodName) throws Exception {
    TestRegistry.registerTestCall(methodName);
    latch.countDown();
    assertTrue(latch.await(RETRY_TIMEOUT_MS, TimeUnit.MILLISECONDS));
  }
}
