// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.provided.subb;

// Only available at compile-time.
import org.pantsbuild.testproject.provided.suba.A;

public class B {

  public static void main(String[] args) {
    A a = new A(); // This should compile, but fail at run-time.
    System.out.println("B was able to instantiate a: " + a);
  }

}