// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Assert;
import org.junit.Assume;
import org.junit.Ignore;
import org.junit.Test;


public class XmlReportTest {
  public static boolean failingTestsShouldFail = false;

  @Test
  public void testXmlPasses() {
    System.out.println("Test output");;
    Assert.assertTrue(true);
  }

  @Test
  public void testXmlFails() {
    Assume.assumeTrue(failingTestsShouldFail);
    Assert.assertTrue(false);
  }

  @Test
  public void testXmlErrors() throws Exception {
    Assume.assumeTrue(failingTestsShouldFail);
    throw new Exception("testXmlErrors exception");
  }

  @Ignore
  @Test
  public void testXmlSkipped() {
    Assert.assertTrue(true);
  }
}
