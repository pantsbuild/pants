// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import org.junit.Test;
import org.pantsbuild.junit.annotations.TestParallel;

/**
 * See {@link AnnotatedParallelTest1}
 */
@TestParallel
public class AnnotatedParallelTest2 {

  @Test
  public void aptest2() throws Exception {
    AnnotatedParallelTest1.awaitLatch("aptest2");
  }
}
