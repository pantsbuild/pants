// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.utf8proto;

class ExampleUtf8Proto {

  private ExampleUtf8Proto() {
  }

  public static void main(String[] args) {
    System.out.println(Utf8.Utf8Example.newBuilder().setValue("¡Hola, Mundo!").build());
  }
}
