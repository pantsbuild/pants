// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.BeforeClass;
import org.junit.Test;

public class ExceptionInSetupTest {
  @BeforeClass
  public static void setUp() {
    throw new RuntimeException();
  }

  @Test
  public void test() {
    // Do nothing.
  }
}
