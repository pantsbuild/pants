// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.base.Predicate;
import com.google.common.collect.Iterables;
import org.junit.Ignore;
import org.junit.runner.Description;
import org.junit.runner.RunWith;
import org.junit.runner.notification.Failure;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;

/**
 * Utilities for working with junit test runs.
 */
final class Util {

  static final Predicate<Method> IS_ANNOTATED_TEST_METHOD =
      new Predicate<Method>() {
        @Override public boolean apply(Method method) {
          return Modifier.isPublic(method.getModifiers())
              && method.isAnnotationPresent(org.junit.Test.class);
        }
      };

  static final Predicate<Constructor<?>> IS_PUBLIC_CONSTRUCTOR =
      new Predicate<Constructor<?>>() {
        @Override public boolean apply(Constructor<?> constructor) {
          return Modifier.isPublic(constructor.getModifiers());
        }
      };

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
   * Returns {@code true} if the given class is {@literal @Ignore}d
   *
   * @param clazz class instance to evaluate.
   * @return {@code true} if the class is marked as ignored.
   */
  static boolean isIgnored(Class<?> clazz) {
    return clazz.isAnnotationPresent(Ignore.class);
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
   * Returns {@code false} if the given class is {@literal @Ignore}d
   *
   * @param clazz class instance to evaluate.
   * @return {@code true} if the class is marked as ignored.
   */
  static boolean isRunnable(Class<?> clazz) {
    return isTestClass(clazz) && !isIgnored(clazz);
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

  /**
   * Returns a sanitized suite name suitable for inclusion in a XML report.
   *
   * This is also used to generate an XML report's filename, so it is important that it does not
   * contain special characters that are illegal on the filesystem.
   *
   * This strips out punction and whitespace, but leaves the '_', '.', and '-' symbols, and trailing
   * periods are trimmed.
   *
   * @param name The name to sanitize. In most cases this is the class name of the test being run,
   *   but some frameworks (I'm looking at you, Cucumber) like to pass weird things like
   *   human-readable free-form textual descriptions of the tests, so we can't make assumptions.
   * @return
   */
  static String sanitizeSuiteName(String name) {
    return name.replaceAll("[[\\p{Punct}][\\p{Space}]&&[^_.-]]", "-").replaceAll("[.]+$", "");
  }

  /**
   * Support junit 3.x Test hierarchy.
   */
  public static boolean isJunit3Test(Class<?> clazz) {
    return junit.framework.Test.class.isAssignableFrom(clazz);
  }

  /**
   * Support classes using junit 4.x custom runners.
   */
  public static boolean isUsingCustomRunner(Class<?> clazz) {
    return clazz.isAnnotationPresent(RunWith.class);
  }

  public static boolean isTestClass(final Class<?> clazz) {
    // Must be a public concrete class to be a runnable junit Test.
    if (clazz.isInterface()
        || Modifier.isAbstract(clazz.getModifiers())
        || !Modifier.isPublic(clazz.getModifiers())) {
      return false;
    }

    // The class must have some public constructor to be instantiated by the runner being used
    if (!Iterables.any(Arrays.asList(clazz.getConstructors()), IS_PUBLIC_CONSTRUCTOR)) {
      return false;
    }

    if (isJunit3Test(clazz)) {
      return true;
    }

    // Support classes using junit 4.x custom runners.
    if (isUsingCustomRunner(clazz)) {
      return true;
    }

    if (ScalaTestUtil.isScalaTestTest(clazz)) {
      return true;
    }

    // Support junit 4.x @Test annotated methods.
    return Iterables.any(Arrays.asList(clazz.getMethods()), IS_ANNOTATED_TEST_METHOD);
  }
}
