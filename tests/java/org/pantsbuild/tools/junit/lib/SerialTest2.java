// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import org.junit.Test;
import org.pantsbuild.junit.annotations.TestSerial;

/**
 * See {@link SerialTest1}
 */
public class SerialTest2 {

  @Test
  public void stest2() throws Exception {
    SerialTest1.awaitLatch("stest2");
  }
}
