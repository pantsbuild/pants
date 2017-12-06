// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.After;
import org.junit.AfterClass;
import org.junit.Assert;
import org.junit.Test;

public class LogOutputInTeardownTest {
  @AfterClass
  public static void tearDown() {
    System.out.println("Output in tearDown");
  }

  @Test
  public void testOne() {
    Assert.assertTrue(true);
  }

  @Test
  public void testTwo() {
    Assert.assertTrue(true);
  }

  @Test
  public void testThree() {
    Assert.assertTrue(true);
  }
}
