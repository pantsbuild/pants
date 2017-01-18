// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.errorprone;

public class ArrayToStringError {
  public static void main(String[] args) {
    int[] a = {1, 2, 3};
    if (a.toString().isEmpty()) {
      System.out.println("int array string is empty");
    }
  }
}
