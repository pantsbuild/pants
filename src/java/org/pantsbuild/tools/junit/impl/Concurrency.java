package org.pantsbuild.tools.junit.impl;

public enum Concurrency {
  SERIAL(false, false),
  PARALLEL_CLASSES(true, false),
  PARALLEL_METHODS(false, true),
  PARALLEL_BOTH(true, true);

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
