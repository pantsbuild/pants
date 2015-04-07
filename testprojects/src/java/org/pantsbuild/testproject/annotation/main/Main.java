// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.annotation.main;

/**
 * We need this so that there is some class that ResourceMappingProcessor can
 * put in to the resource-mappings file.  It's marked @Deprecated because it
 * needs to be annotated with something so that the annotation processor gets
 * run, and Deprecated is built-in to java.
 */
@Deprecated
public class Main {
  public static void main(String args[]) {
    System.out.println("Hello World!");
  }

  /**
   * Inner class marked with annotation.
   */
  @Deprecated
  private static class TestInnerClass {
  }
}
