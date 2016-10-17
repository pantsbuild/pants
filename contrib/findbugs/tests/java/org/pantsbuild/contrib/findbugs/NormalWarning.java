// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.contrib.findbugs;

public class NormalWarning {
  public static void main(String[] args) {
    String normal = null;
    System.out.printf("FindBugs Normal Warning NP_ALWAYS_NULL: %d", normal.length());
  }
}
