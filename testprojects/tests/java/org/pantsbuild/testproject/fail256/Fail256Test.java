// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.testrule;

import org.junit.Assert;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;
import org.junit.runners.Parameterized.Parameter;
import org.junit.runners.Parameterized.Parameters;

@RunWith(Parameterized.class)
public class Fail256Test {

  @Parameters
  public static Object[] data() {
    Object[] parameters = new Object[256];
    for (int i = 0; i < 256; i++) {
      parameters[i] = i;
    }
    return parameters;
  }

  @Parameter
  public int input;

  @Test
  public void testFails() {
    Assert.assertTrue(input < 0);
  }
}
