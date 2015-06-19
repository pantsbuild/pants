// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Test;

public class MockTest4 {

  @Test
  public void testMethod41() {
    TestRegistry.registerTestCall("test41");
    System.out.println("test41");
  }

  @Test
  public void testMethod42() {
    System.out.println("start test42");
    TestRegistry.registerTestCall("test42");
    System.out.println("end test42");
  }
}
