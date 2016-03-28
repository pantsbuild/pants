// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.junit.testscope;

public class CheckForLibrary {

  public static boolean check() {
    try {
      Class<?> cls = Class.forName("org.pantsbuild.testproject.junit.testscope.SomeLibraryFile");
      return cls.getSimpleName().equals("SomeLibraryFile");
    } catch (ClassNotFoundException ex) {
      throw new RuntimeException(ex);
    }
  }

  public static void main(String[] args) {
    check();
  }

}