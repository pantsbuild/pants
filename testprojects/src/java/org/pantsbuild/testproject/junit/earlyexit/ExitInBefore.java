// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.junit.earlyexit;

import org.junit.Before;
import org.junit.Test;

public class ExitInBefore {
  @Before
  public void exitBefore() {
    System.exit(0);
  }

  @Test
  public void test1() {
    // pass
  }
}
