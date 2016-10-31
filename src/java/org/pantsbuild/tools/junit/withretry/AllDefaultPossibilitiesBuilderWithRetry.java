// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.withretry;

import java.io.PrintStream;

import org.junit.internal.builders.AllDefaultPossibilitiesBuilder;
import org.junit.internal.builders.AnnotatedBuilder;
import org.junit.internal.builders.JUnit4Builder;
import org.junit.runner.Runner;
import org.junit.runners.model.RunnerBuilder;

/**
 * Needed to support retrying flaky tests. Using method overriding, gives us access to code
 * in JUnit4 that cannot be customized in a simpler way.
 */
public class AllDefaultPossibilitiesBuilderWithRetry extends AllDefaultPossibilitiesBuilder {

  private final int numRetries;
  private final PrintStream err;

  public AllDefaultPossibilitiesBuilderWithRetry(int numRetries, PrintStream err) {
    super(true);
    this.numRetries = numRetries;
    this.err = err;
  }

  @Override
  public JUnit4Builder junit4Builder() {
    return new JUnit4BuilderWithRetry(numRetries, err);
  }

  // override annotated builder to "fake" the scala test junit runner for scala tests
  @Override
  protected AnnotatedBuilder annotatedBuilder() {
    return new ScalaTestAnnotatedBuilder(this);
  }

  private static class ScalaTestAnnotatedBuilder extends AnnotatedBuilder {
    ScalaTestAnnotatedBuilder(RunnerBuilder suiteBuilder) {
      super(suiteBuilder);
    }

    @Override
    public Runner runnerForClass(Class<?> testClass) throws Exception {
      Runner runner = super.runnerForClass(testClass);
      if (runner == null) {
        if (ScalaTestUtil.isScalaTestTest(testClass)) {
          return ScalaTestUtil.getJUnitRunner(testClass);
        }
      }
      return runner;
    }
  }
}
