// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import java.util.List;
import org.junit.rules.TestRule;
import org.junit.runners.BlockJUnit4ClassRunner;
import org.junit.runners.model.InitializationError;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class FailingTestRunner extends BlockJUnit4ClassRunner {
  public FailingTestRunner(Class<?> klass) throws InitializationError {
    super(klass);
  }

  @Override protected List<TestRule> getTestRules(Object target) {
    throw new RuntimeException("failed in getTestRules");
  }
}
