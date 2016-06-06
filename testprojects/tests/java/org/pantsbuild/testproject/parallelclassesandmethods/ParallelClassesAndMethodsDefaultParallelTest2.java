// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.parallelclassesandmethods;

import org.junit.Test;

/**
 * See {@link ParallelClassesAndMethodsDefaultParallelTest1}
 */
public class ParallelClassesAndMethodsDefaultParallelTest2 {

  @Test
  public void pbdptest21() throws Exception {
    ParallelClassesAndMethodsDefaultParallelTest1.awaitLatch("pbdptest21");
  }

  @Test
  public void pbdptest22() throws Exception {
    ParallelClassesAndMethodsDefaultParallelTest1.awaitLatch("pbdptest22");
  }
}
