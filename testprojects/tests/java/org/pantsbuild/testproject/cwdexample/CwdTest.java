// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cwdexample;
// Tests the --cwd option for running tests

import java.io.File;

import com.google.common.base.Joiner;
import org.junit.Test;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;


public class CwdTest {
  @Test
  public void testChangedCwd() {
    // We don't want this to fail for pants goal testprojects::, so we're going to
    // conditionalize on a system property
    String cwdTestEnabledFlag = System.getProperty("cwd.test.enabled");
    boolean cwdTestEnabled = cwdTestEnabledFlag == null ? false :
        cwdTestEnabledFlag.toLowerCase().equals("true");
    if (cwdTestEnabled) {
      if (testSourceExists()) {
        System.out.println("Found " + EXAMPLE_TEST_SOURCE);
      } else if (ExampleCwd.resourceExists()) {
        System.out.println("Found " + ExampleCwd.EXAMPLE_TEXT);
      } else {
        // Including Joiner simply to get a 3rdparty jar on the classpath for testing.
        Joiner joiner = Joiner.on(" ");
        fail(joiner.join(
            "Error: Neither", EXAMPLE_TEST_SOURCE, "nor", ExampleCwd.EXAMPLE_TEXT, "found. cwd=",
            System.getProperty("user.dir")));
      }
    } else {
      // allow test to pass.
    }
  }

  private static final String EXAMPLE_TEST_SOURCE=CwdTest.class.getSimpleName() + ".java";

  public static boolean testSourceExists() {
    File f = new File(EXAMPLE_TEST_SOURCE);
    return f.exists();
  }
}
