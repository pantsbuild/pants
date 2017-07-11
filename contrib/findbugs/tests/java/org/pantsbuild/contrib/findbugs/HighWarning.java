// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.findbugs;

public class HighWarning {
  @SuppressWarnings("EqualsIncompatibleType")
  public static void main(String[] args) {
    String high = "string";
    System.out.println("FindBugs High Warning EC_UNRELATED_TYPES:" + high.equals(high.length()));
  }
}
