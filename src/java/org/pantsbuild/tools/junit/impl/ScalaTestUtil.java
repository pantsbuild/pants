package org.pantsbuild.tools.junit.impl;

import org.junit.runner.Runner;

public final class ScalaTestUtil {
  private ScalaTestUtil() {}

   // Scalatest classes loaded once with runtime reflection to avoid the extra
   // dependency.
  private static Class<?> suiteClass = null;
  private static Class<?> junitRunnerClass = null;
  static {
    try {
      suiteClass = Class.forName("org.scalatest.Suite");
      junitRunnerClass = Class.forName("org.scalatest.junit.JUnitRunner");
    } catch (ClassNotFoundException e) {
      // No scalatest tests on classpath
    }
  }

  /**
   * Returns a scalatest junit runner using reflection.
   * @param clazz the test class
   *
   * @return a new scala test junit runner
   */
  public static Runner getJUnitRunner(Class<?> clazz) {
    try {
      return (Runner) junitRunnerClass.getConstructor(Class.class).newInstance(clazz);
    } catch (Exception e) {
      // isScalaTest should fail if scala test isn't available so this is probably ok.
      throw new RuntimeException(e);
    }
  }

  /**
   * Checks if the passed in test clazz has an ancestor that is the scala test suite
   * trait.
   * @param clazz the test class
   *
   * @return true if the test class is a scalatest test, false if not.
   */
  public static boolean isScalaTestTest(Class<?> clazz) {
    return suiteClass != null && suiteClass.isAssignableFrom(clazz);
  }
}
