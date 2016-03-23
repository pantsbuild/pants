// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.Assert;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
@RunWith(FailingTestRunner.class)
public class XmlReportFailingTestRunnerTest {
  @Test
  public void testXmlPassing() {
    Assert.assertTrue(true);
  }
}
