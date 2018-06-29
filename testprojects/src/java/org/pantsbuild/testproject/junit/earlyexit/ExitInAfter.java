// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.junit.earlyexit;

import org.junit.After;
import org.junit.Test;

public class ExitInAfter {
  @After
  public void exitAfter() {
    System.exit(0);
  }

  @Test
  public void test1() {
    // pass
  }
}
