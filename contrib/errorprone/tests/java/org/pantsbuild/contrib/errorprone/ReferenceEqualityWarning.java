// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.errorprone;

public class ReferenceEqualityWarning {
  public static void main(String[] args) {
    if (args[0] == "one") {
      System.out.println("You should use equals() instead");
    }
  }
}
