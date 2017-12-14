// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import org.junit.After;
import org.junit.AfterClass;
import org.junit.Assert;
import org.junit.Before;
import org.junit.BeforeClass;
import org.junit.Ignore;
import org.junit.Test;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
public class OutputModeTest {
  @BeforeClass
  public static void classSetUp() {
    System.out.println("Output in classSetUp");
  }

  @Before
  public void setUp() {
    System.out.println("Output in setUp");
  }

  @After
  public void tearDown() {
    System.out.println("Output in tearDown");
  }

  @AfterClass
  public static void classTearDown() {
    System.out.println("Output in classTearDown");
  }

  @Test
  public void testPasses() {
    System.out.println("Output from passing test");
    Assert.assertTrue(true);
  }

  @Test
  public void testFails() {
    System.out.println("Output from failing test");
    Assert.assertTrue(false);
  }

  @Test
  public void testErrors() throws Exception {
    System.out.println("Output from error test");
    throw new Exception("testErrors exception");
  }

  @Ignore
  @Test
  public void testSkipped() {
    System.out.println("Output from ignored test");
    Assert.assertTrue(true);
  }
}
