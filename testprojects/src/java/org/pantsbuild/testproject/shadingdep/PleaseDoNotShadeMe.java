// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.shadingdep;

/**
 * Used to test shading support in tests/python/pants_test/java/jar/test_shader_integration.py
 */
public class PleaseDoNotShadeMe {
  public static void sayPlease() {
    System.out.println("PleaseDoNotShadeMe: " + PleaseDoNotShadeMe.class.getName());
  }
}
