// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.manifest;

public class Manifest {
  public static void main(String args[]) {
    System.out.println("Hello World!  Version: "
      + Package.getPackage("org.pantsbuild.testproject.manifest").getImplementationVersion());
  }
}
