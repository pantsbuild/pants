// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Test;

public class MockTest3 {

  @Test
  public void testMethod31() {
    TestRegistry.registerTestCall("test31");
  }

  @Test
  public void testMethod32() {
    TestRegistry.registerTestCall("test32");
  }
}
