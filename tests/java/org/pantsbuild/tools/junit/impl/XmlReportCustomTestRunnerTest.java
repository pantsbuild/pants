// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Assert;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(CustomTestRunner.class)
public class XmlReportCustomTestRunnerTest {
  @Test
  public void testXmlPassing() {
    Assert.assertTrue(true);
  }
}
