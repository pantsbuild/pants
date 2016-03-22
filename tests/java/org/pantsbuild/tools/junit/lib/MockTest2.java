// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
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
