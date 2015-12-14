// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Assert;
import org.junit.Test;

/**
 * Tests several recently added features in ConsoleRunner.
 * TODO: cover the rest of ConsoleRunner functionality.
 */
public class ConsoleRunnerTest extends ConsoleRunnerTestHelper{

  @Test
  public void testNormalTesting() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3"));
    Assert.assertEquals("test11 test12 test13 test21 test22 test31 test32",
        TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting02() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 0/2"));
    Assert.assertEquals("test11 test13 test22 test32", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting13() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("MockTest1 MockTest2 MockTest3 -test-shard 1/3"));
    Assert.assertEquals("test12 test22", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23() throws Exception {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3"));
    Assert.assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting12WithParallelThreads() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 1/2 -parallel-threads 4 -default-parallel"));
    Assert.assertEquals("test12 test21 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testShardedTesting23WithParallelThreads() throws Exception {
    // This tests a corner case when no tests from MockTest2 are going to run.
    ConsoleRunnerImpl.main(asArgsArray(
        "MockTest1 MockTest2 MockTest3 -test-shard 2/3 -parallel-threads 3 -default-parallel"));
    Assert.assertEquals("test13 test31", TestRegistry.getCalledTests());
  }

  @Test
  public void testFlakyTests() throws Exception {
    TestRegistry.consoleRunnerTestRunsFlakyTests = true;
    FlakyTest.numFlakyTestInstantiations = 0;
    FlakyTest.numExpectedExceptionMethodInvocations = 0;

    try {
      ConsoleRunnerImpl.main(asArgsArray("FlakyTest -num-retries 2"));
      Assert.fail("Should have failed with RuntimeException due to FlakyTest.methodAlwaysFails");
      // FlakyTest.methodAlwaysFails fails this way - though perhaps that should be fixed to be an
      // RTE subclass.
      // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    } catch (RuntimeException ex) {
      // Expected due to FlakyTest.methodAlwaysFails()
    } finally {
      TestRegistry.consoleRunnerTestRunsFlakyTests = false;
    }

    Assert.assertEquals("expected_ex flaky1 flaky1 flaky2 flaky2 flaky2 flaky3 flaky3 flaky3 "
        + "notflaky", TestRegistry.getCalledTests());

    // Verify that FlakyTest class has been instantiated once per test method invocation,
    // including flaky test method invocations.
    Assert.assertEquals(10, FlakyTest.numFlakyTestInstantiations);

    // Verify that a method with expected exception is not treated
    // as flaky - that is, it should be invoked only once.
    Assert.assertEquals(1, FlakyTest.numExpectedExceptionMethodInvocations);
  }

  @Test
  public void testTestCase() throws Exception {
    ConsoleRunnerImpl.main(asArgsArray("SimpleTestCase"));
    Assert.assertEquals("testDummy", TestRegistry.getCalledTests());
  }
}
