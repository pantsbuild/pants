// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Test;

public class MockTest2 {

  @Test
  public void testMethod21() {
    TestRegistry.registerTestCall("test21");
  }

  @Test
  public void testMethod22() {
    TestRegistry.registerTestCall("test22");
  }
}
