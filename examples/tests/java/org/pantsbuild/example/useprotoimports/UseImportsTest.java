// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Illustrate using Proto-generated code from Java.

package org.pantsbuild.example.useprotoimports;

import org.junit.Assert;
import org.junit.Test;

import org.pantsbuild.example.imports.TestImports;

public class UseImportsTest {
  @Test
  public void checkDistanceExistence() {
    String value = TestImports.TestImport.newBuilder().setTestNum(19).setTestStr("legions").build()
        .toString();
    Assert.assertTrue("TestImports string value (" + value + ")", value.contains("legions"));
  }
}

