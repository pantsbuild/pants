// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.htmlreport;

import org.junit.Assert;
import org.junit.Ignore;
import org.junit.Test;

public class HtmlReportTest {
  @Test
  public void testPasses() {
    System.out.println("Test output");
    Assert.assertTrue(true);
  }

  @Test
  public void testFails() {
    Assert.assertTrue(false);
  }

  @Test
  public void testErrors() throws Exception {
    throw new Exception("testErrors exception");
  }

  @Ignore
  @Test
  public void testSkipped() {
    Assert.assertTrue(true);
  }
}
