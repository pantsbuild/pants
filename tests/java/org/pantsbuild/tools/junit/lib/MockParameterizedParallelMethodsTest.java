// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;

import static org.junit.Assert.assertTrue;

@RunWith(Parameterized.class)
public class MockParameterizedParallelMethodsTest {
  private static final int NUM_CONCURRENT_TESTS = 3;
  private static final int RETRY_TIMEOUT_MS = 1000;
  private static CountDownLatch latch = new CountDownLatch(NUM_CONCURRENT_TESTS);

  private String parameter;

  public static void reset() {
    latch = new CountDownLatch(NUM_CONCURRENT_TESTS);
  }

  @Parameterized.Parameters
  public static List<String> data() {
    return Arrays.asList("one", "two", "three");
  }

  public MockParameterizedParallelMethodsTest(String parameter) {
    this.parameter = parameter;
  }

  @Test
  public void ppmtest1() throws Exception {
    awaitLatch("ppmtest1:" + parameter);
  }

  static void awaitLatch(String methodName) throws Exception {
    TestRegistry.registerTestCall(methodName);
    latch.countDown();
    assertTrue(latch.await(RETRY_TIMEOUT_MS, TimeUnit.MILLISECONDS));
  }
}
