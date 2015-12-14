// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.shading;

/**
 * Used to test shading support in tests/python/pants_test/java/jar/test_shader_integration.py
 */
public class ShadeSelf {
  public static void sayHi() {
    System.out.println("ShadeSelf says hi: " + ShadeSelf.class.getName());
  }
}
