// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

/**
 * Describes the type of concurrency desired when running a batch of tests.
 */
public enum Concurrency {
  SERIAL(false, false),
  PARALLEL_CLASSES(true, false),
  PARALLEL_METHODS(false, true),
  PARALLEL_CLASSES_AND_METHODS(true, true);

  private final boolean parallelClasses;
  private final boolean parallelMethods;

  Concurrency(boolean parallelClasses, boolean parallelMethods) {
    this.parallelClasses = parallelClasses;
    this.parallelMethods = parallelMethods;
  }

  public boolean shouldRunClassesParallel() {
    return parallelClasses;
  }

  public boolean shouldRunMethodsParallel() {
    return parallelMethods;
  }
}
