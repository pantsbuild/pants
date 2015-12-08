// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner.testproject;

import java.util.Arrays;

public class MainClass {
  public static void main(String[] args) {
    System.out.println(DependentClass.getDependentClassMessage() + " " + Arrays.toString(args));
  }
}
