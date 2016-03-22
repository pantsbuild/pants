// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import junit.framework.TestCase;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class SimpleTestCase extends TestCase {
  public void testDummy() {
    TestRegistry.registerTestCall("testDummy");
    assertTrue(true);
  }
}
