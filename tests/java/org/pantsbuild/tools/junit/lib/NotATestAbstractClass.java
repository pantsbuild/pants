// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.tools.junit.lib;

import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public abstract class NotATestAbstractClass {

  // Even though annotated with @Test, this is an abstract class, so the test shouldn't be invoked
  @Test
  public void natac1() {
    TestRegistry.registerTestCall("natac1");
  }
}
