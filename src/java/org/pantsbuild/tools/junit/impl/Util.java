// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Ignore;
import org.junit.runner.Description;
import org.junit.runner.notification.Failure;

/**
 * Utilities for working with junit test runs.
 */
final class Util {

  private Util() {
    // utility
  }

  /**
   * Returns {@code true} if the given {@code test} is {@literal @Ignore}d.
   *
   * @param test The test description to evaluate.
   * @return {@code true} if the described test is marked as ignored.
   */
  static boolean isIgnored(Description test) {
    return test.getAnnotation(Ignore.class) != null;
  }

  /**
   * Returns {@code true} if the given {@code test} is eligible for running.  Runnable tests are
   * those that are not {@literal @Ignore}d and have direct executable content (i.e.: not a test
   * suite or other executable test aggregator).
   *
   * @param test The test description to evaluate.
   * @return {@code true} if the described test will be run by a standard junit runner.
   */
  static boolean isRunnable(Description test) {
    return test.isTest() && !isIgnored(test);
  }

  /**
   * Returns {@code true} if the test failure represents an assertion failure.
   *
   * @param failure The failure to test.
   * @return {@code true} if the failure was from an incorrect assertion, {@code false} otherwise.
   */
  static boolean isAssertionFailure(Failure failure) {
    return failure.getException() instanceof AssertionError;
  }

  /**
   * Returns a pants-friendly formatted description of the test-case.
   *
   * Pants likes test-cases formatted as org.foo.bar.TestClassName#testMethodName
   *
   * @param description The test description to produce a formatted name for.
   * @return The formatted name of the test-case, if possible. If the Description does not have a
   * class name or a method name, falls back on the description.getDisplayName().
   */
  static String getPantsFriendlyDisplayName(Description description) {
    String className = description.getClassName();
    String methodName = description.getMethodName();
    String vanillaDisplayName = description.getDisplayName();
    if (className.equals(vanillaDisplayName) || methodName.equals(vanillaDisplayName)) {
      // This happens if the Description isn't actually describing a test method. We don't handle
      // this, so just use the default formatting.
      return vanillaDisplayName;
    }

    StringBuffer sb = new StringBuffer(className.length() + methodName.length() + 1);
    sb.append(className);
    sb.append("#");
    sb.append(methodName);
    return sb.toString();
  }

}
