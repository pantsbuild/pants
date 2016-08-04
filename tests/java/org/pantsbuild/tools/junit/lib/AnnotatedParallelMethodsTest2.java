// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import org.junit.Test;
import org.pantsbuild.junit.annotations.TestParallelMethods;

/**
 * See {@link AnnotatedParallelMethodsTest1}
 */
@TestParallelMethods
public class AnnotatedParallelMethodsTest2 {

  @Test
  public void apmtest21() throws Exception {
    AnnotatedParallelMethodsTest1.awaitLatch("apmtest21");
  }

  @Test
  public void apmtest22() throws Exception {
    AnnotatedParallelMethodsTest1.awaitLatch("apmtest22");
  }
}
