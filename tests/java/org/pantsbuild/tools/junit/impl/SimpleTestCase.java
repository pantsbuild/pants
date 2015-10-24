// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import junit.framework.TestCase;

public class SimpleTestCase extends TestCase {
  public void testDummy() {
    TestRegistry.registerTestCall("testDummy");
    assertTrue(true);
  }
}
