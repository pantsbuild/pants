// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.syntheticjar.run;

public class SyntheticJarRun {
  public static void main(String[] args) {
    org.pantsbuild.testproject.syntheticjar.util.Util.detectSyntheticJar();
  }
}
