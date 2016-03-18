// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.util.ArrayList;
import java.util.List;
import org.junit.rules.TestRule;
import org.junit.runners.BlockJUnit4ClassRunner;
import org.junit.runners.model.InitializationError;

public class CustomTestRunner extends BlockJUnit4ClassRunner {
  public static boolean shouldFailDuringInitialization = false;

  public CustomTestRunner(Class<?> klass) throws InitializationError {
    super(klass);
  }

  @Override protected List<TestRule> getTestRules(Object target) {
    if (shouldFailDuringInitialization) {
      throw new RuntimeException("failed in getTestRules");
    }
    return new ArrayList<TestRule>();
  }
}
