package org.pantsbuild.tools.junit.impl;

import org.junit.runner.Description;
import org.junit.runner.Runner;
import org.junit.runner.manipulation.Filter;
import org.junit.runner.manipulation.Filterable;
import org.junit.runner.manipulation.NoTestsRemainException;
import org.junit.runner.notification.RunNotifier;

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
   * This is added temporarily to fix the sharding of scala tests
   * Issue: https://github.com/pantsbuild/pants/issues/8594
   * TODO: Remove this when https://github.com/scalatest/scalatestplus-junit/pull/8 is merged
   */
  private static class ScalaTestJunitRunnerWrapper extends Runner implements Filterable {
      private Runner delegate;
      private Class<?> suite;

      private ScalaTestJunitRunnerWrapper(Runner delegate, Class<?> suite) {
        this.delegate = delegate;
        this.suite = suite;
      }

      @Override
      public Description getDescription() {
          return Description.createSuiteDescription(suite);
      }

      @Override
      public void run(RunNotifier notifier) {
          delegate.run(notifier);
      }

      @Override
      public void filter(Filter filter) throws NoTestsRemainException {
        if (!filter.shouldRun(getDescription())) throw new NoTestsRemainException();
      }
  }

  /**
   * Returns a scalatest junit runner using reflection.
   * @param clazz the test class
   *
   * @return a new scalatest junit runner
   */
  public static Runner getJUnitRunner(Class<?> clazz) throws Exception {
    return new ScalaTestJunitRunnerWrapper(
            (Runner) junitRunnerClass.getConstructor(Class.class).newInstance(clazz), clazz);
  }

  /**
   * Checks if the passed in test clazz has an ancestor that is the scalatest suite
   * trait.
   * @param clazz the test class
   *
   * @return true if the test class is a scalatest test, false if not.
   */
  public static boolean isScalaTestTest(Class<?> clazz) {
    return suiteClass != null && suiteClass.isAssignableFrom(clazz);
  }
}
