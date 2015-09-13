// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.annotation.processorwithdep.main;

import org.pantsbuild.testproject.annotation.processorwithdep.hellomaker.HelloMaker;

@HelloMaker
public class Main {
  public static void main() {
    System.out.println("Hello World!");
  }
}
