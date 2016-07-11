// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.After;
import org.junit.Assert;
import org.junit.Before;
import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class FlakyTest {
  public static int numFlaky1Invocations = 0;
  public static int numFlaky2Invocations = 0;
  public static int numFlaky3Invocations = 0;
  public static int numExpectedExceptionMethodInvocations = 0;
  public static int numFlakyTestInstantiations = 0;

  public int numTestMethodInvocationsPerTestInstance;

  public static void reset() {
    numFlaky1Invocations = 0;
    numFlaky2Invocations = 0;
    numFlaky3Invocations = 0;
    numExpectedExceptionMethodInvocations = 0;
    numFlakyTestInstantiations = 0;
  }

  public FlakyTest() {
    numFlakyTestInstantiations++;
  }

  // Checks in Before/After methods ensure that when a flaky test is retried,
  // a test object (an instance of FlakyTest class) is re-instantiated. If that
  // didn't happen, we could have seen numTestMethodInvocationsPerTestInstance
  // greater than 1 in after/tearDown.
  @Before
  public void before() {
    Assert.assertEquals(0, numTestMethodInvocationsPerTestInstance);
  }

  @After
  public void after() {
    Assert.assertEquals(1, numTestMethodInvocationsPerTestInstance);
  }

  @Test
  public void flakyMethodSucceedsAfter1Retry() throws Exception {
    numTestMethodInvocationsPerTestInstance++;
    TestRegistry.registerTestCall("flaky1");
    numFlaky1Invocations++;
    if (numFlaky1Invocations < 2) {
      throw new Exception("flaky1 failed on invocation number " + numFlaky1Invocations);
    }
  }

  @Test
  public void flakyMethodSucceedsAfter2Retries() throws Exception {
    numTestMethodInvocationsPerTestInstance++;
    TestRegistry.registerTestCall("flaky2");
    numFlaky2Invocations++;
    if (numFlaky2Invocations < 3) {
      throw new Exception("flaky2 failed on invocation number " + numFlaky2Invocations);
    }
  }

  @Test
  public void methodAlwaysFails() throws Exception {
    numTestMethodInvocationsPerTestInstance++;
    TestRegistry.registerTestCall("flaky3");
    numFlaky3Invocations++;
    throw new Exception("flaky3 failed on invocation number " + numFlaky3Invocations);
  }

  @Test
  public void notFlakyMethod() {
    numTestMethodInvocationsPerTestInstance++;
    TestRegistry.registerTestCall("notflaky");
  }

  @Test(expected = CustomException.class)
  public void methodWithExpectedException() throws Exception {
    numTestMethodInvocationsPerTestInstance++;
    numExpectedExceptionMethodInvocations++;
    TestRegistry.registerTestCall("expected_ex");
    throw new CustomException("This is expected");
  }

  public static class CustomException extends Exception {

    CustomException(String message) {
      super(message);
    }
  }
}
