// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import java.util.Arrays;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;

@RunWith(Parameterized.class)
public class MockParameterizedParallelClassesAndMethodsTest2 {
  private String parameter;

  @Parameterized.Parameters
  public static List<String> data() {
    return Arrays.asList("arg1", "arg2");
  }

  public MockParameterizedParallelClassesAndMethodsTest2(String parameter) {
    this.parameter = parameter;
  }
  @Test
  public void ppcamtest2() throws Exception {
    MockParameterizedParallelClassesAndMethodsTest1.awaitLatch("ppcamtest2:" + parameter);
  }
}
