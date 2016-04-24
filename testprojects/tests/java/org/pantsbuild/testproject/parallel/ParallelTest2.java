// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.parallel;

import org.junit.Test;

/**
 * See {@link ParallelTest1}
 */
public class ParallelTest2 {

  @Test
  public void ptest2() throws Exception {
    ParallelTest1.awaitLatch("ptest2");
  }
}
