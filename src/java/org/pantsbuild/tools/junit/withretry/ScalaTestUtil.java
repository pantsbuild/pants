package org.pantsbuild.tools.junit.withretry;

import org.junit.runner.Runner;

public class ScalaTestUtil {
  /**
   * Returns a scalatest junit runner using reflection in the classloader of the test.
   * @param clazz the test class
   * @return a new scala test junit runner
   */
  public static Runner getJUnitRunner(Class<?> clazz) {
    try {
      Class<?> junitRunnerClass = Class.forName("org.scalatest.junit.JUnitRunner",
          true, clazz.getClassLoader());
      return (Runner)junitRunnerClass.getConstructor(Class.class).newInstance(clazz);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  /**
   * Checks if the passed in test clazz has an ancestor that is the scala test suite
   * object (looked up in the test classes class loader).
   * @param clazz the test class
   * @return true if the test class is a scalatest test, false if not.
   */
  public static boolean isScalaTestTest(Class<?> clazz) {
    try {
      Class suiteClass = Class.forName("org.scalatest.Suite", true, clazz.getClassLoader());
      return suiteClass.isAssignableFrom(clazz);
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }
}
