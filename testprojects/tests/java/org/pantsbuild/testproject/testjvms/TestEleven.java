// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.testjvms;

import org.junit.Test;

/**
 * Ensure this test is run with java 1.11.
 * */
public class TestEleven extends TestBase {
  @Test
  public void testEleven() {
    assertJavaVersion("1.11");
  }
}
