// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Assert;
import org.junit.Before;
import org.junit.Test;

public class XmlReportFailInSetupTest {
  public static boolean shouldFailDuringSetup = false;

  @Before
  public void setUp() throws Exception {
    if (shouldFailDuringSetup) {
      throw new Exception("Fail in setUp");
    }
  }

  @Test
  public void testXmlPassing() {
    Assert.assertTrue(true);
  }

  @Test
  public void testXmlPassingAgain() {
    Assert.assertTrue(true);
  }
}
