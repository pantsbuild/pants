// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import org.junit.Test;
import org.pantsbuild.junit.annotations.TestSerial;

/**
 * See {@link AnnotatedSerialTest1}
 */
@TestSerial
public class AnnotatedSerialTest2 {

  @Test
  public void astest2() throws Exception {
    AnnotatedSerialTest1.awaitLatch("astest2");
  }
}
