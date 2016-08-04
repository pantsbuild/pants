// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Test;

import static org.hamcrest.core.Is.is;
import static org.junit.Assert.assertTrue;
import static org.junit.Assume.assumeThat;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class XmlReportAssumeTest {
  @Test
  public void testIgnoredByAssumeThat() {
    assumeThat(0, is(1));
    assertTrue(false);
  }

  @Test
  public void testPassing() {
    assumeThat(1, is(1));
    assertTrue(true);
  }

  @Test
  public void testFailing() {
    assumeThat(1, is(1));
    assertTrue(false);
  }
}
