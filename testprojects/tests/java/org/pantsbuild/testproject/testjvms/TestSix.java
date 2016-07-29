// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.testjvms;

import org.junit.Test;

/**
 * Ensure this test is run with java 1.6.
 * */
public class TestSix extends TestBase {
  @Test
  public void testSix() {
    assertJavaVersion("1.6");
  }
}
