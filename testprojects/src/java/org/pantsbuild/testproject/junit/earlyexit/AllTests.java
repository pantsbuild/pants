// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.junit.earlyexit;

import org.junit.Test;

public class AllTests {
  @Test
  public void testExitOne() {
    System.exit(0);
  }

  @Test
  public void testExitTwo() {
    System.exit(0);
  }
}
