// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class NotATestNoPublicConstructor {

  private NotATestNoPublicConstructor() {
  }

  // No public constructor for this class, so the test shouldn't be invoked
  public void natnpc1() {
    TestRegistry.registerTestCall("natnpc1");
  }
}
