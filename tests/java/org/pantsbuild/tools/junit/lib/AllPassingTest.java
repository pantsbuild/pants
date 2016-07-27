// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Assert;
import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class AllPassingTest {
  @Test
  public void testPassesOne() {
    Assert.assertTrue(true);
  }

  @Test
  public void testPassesTwo() {
    Assert.assertTrue(true);
  }

  @Test
  public void testPassesThree() {
    Assert.assertTrue(true);
  }

  @Test
  public void testPassesFour() {
    Assert.assertTrue(true);
  }
}
