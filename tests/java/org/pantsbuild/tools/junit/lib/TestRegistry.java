// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * This is used by each of our mock tests to register the fact that it was called.
 * Unfortunately, we have to use a static API, and explicit reset() call is needed
 * every time before running a new real test. Trying to use a singleton object seems
 * to cause more problems than it fixes, since our MockTestX are called independently
 * by pants, and they may catch TestRegistry singleton in uninitialized state.
 */
final public class TestRegistry {
  private static List<String> testsCalled = new ArrayList<String>();

  // No instances of this classes can be constructed
  private TestRegistry() { }

  public static synchronized void registerTestCall(String testId) {
    testsCalled.add(testId);
  }

  public static synchronized void reset() {
    testsCalled.clear();
  }

  /** Returns the called tests in sorted order as a single string */
  public static String getCalledTests() {
    return getCalledTests(true);
  }

  public static synchronized String getCalledTests(boolean sort) {
    if (testsCalled.isEmpty()) {
      return "";
    }

    String[] tests = testsCalled.toArray(new String[testsCalled.size()]);
    if (sort) {
      Arrays.sort(tests);
    }
    StringBuilder sb = new StringBuilder(50);
    sb.append(tests[0]);
    for (int i = 1; i < tests.length; i++) {
      sb.append(' ').append(tests[i]);
    }
    return sb.toString();
  }
}
