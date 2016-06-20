// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Before;
import org.junit.Test;

import static org.hamcrest.core.Is.is;
import static org.junit.Assert.assertTrue;
import static org.junit.Assume.assumeThat;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class XmlReportAssumeSetupTest {
  @Before
  public void setUp() throws Exception {
    assumeThat(0, is(1));
  }

  @Test
  public void testPassing() {
    assertTrue(true);
  }

  @Test
  public void testFailing() {
    assertTrue(false);
  }
}
