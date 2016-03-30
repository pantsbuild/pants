// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
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
