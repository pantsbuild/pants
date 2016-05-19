// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.findbugs;

public class AllWarnings {
  public static void main(String[] args) {
    System.out.println("No FindBugs warnings");

    System.out.printf("FindBugs Low Warning VA_FORMAT_STRING_USES_NEWLINE: \n");

    String normal = null;
    System.out.printf("FindBugs Normal Warning NP_ALWAYS_NULL: %d", normal.length());

    String high = "string";
    System.out.println("FindBugs High Warning EC_UNRELATED_TYPES:" + high.equals(high.length()));
  }
}
