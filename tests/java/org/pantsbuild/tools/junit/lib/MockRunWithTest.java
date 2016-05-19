// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;
import org.junit.runners.Parameterized.Parameters;


/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
@RunWith(Parameterized.class)
public class MockRunWithTest {
  private String parameter;

  @Parameters
  public static List<String> data() {
    return Arrays.asList("foo", "bar");
  }

  public MockRunWithTest(String parameter) {
    this.parameter = parameter;
  }

  @Test
  public void mrwt1() {
    TestRegistry.registerTestCall("mrwt1-" + parameter);
  }
}
