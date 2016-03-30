// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Assert;
import org.junit.Ignore;
import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
@Ignore
public class XmlReportIgnoredTestSuiteTest {
  @Test
  public void testXmlPassing() {
    Assert.assertTrue(true);
  }

  @Test
  public void testXmlFailing() {
    Assert.assertTrue(false);
  }
}
