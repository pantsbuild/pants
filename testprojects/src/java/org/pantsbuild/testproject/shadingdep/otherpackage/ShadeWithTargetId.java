// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.shadingdep.otherpackage;

/**
 * Used to test shading support in tests/python/pants_test/java/jar/test_shader_integration.py
 */
public class ShadeWithTargetId {
  public static void main(String[] args) {
    System.out.println("ShadeWithTargetId: " + ShadeWithTargetId.class.getName());
  }
}
