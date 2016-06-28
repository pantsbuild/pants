// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import org.junit.Test;
import org.pantsbuild.junit.annotations.TestParallelClassesAndMethods;

/**
 * See {@link AnnotatedParallelClassesAndMethodsTest1}
 */
@TestParallelClassesAndMethods
public class AnnotatedParallelClassesAndMethodsTest2 {

  @Test
  public void apcamtest21() throws Exception {
    AnnotatedParallelClassesAndMethodsTest1.awaitLatch("apcamtest21");
  }
  @Test
  public void apcamtest22() throws Exception {
    AnnotatedParallelClassesAndMethodsTest1.awaitLatch("apcamtest22");
  }
}
