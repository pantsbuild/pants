// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.npm_module;


public class HelloMain {

  public static void main(String[] args) {
    // Target of greeting is config'd in greetee.txt file, so read that:
    System.out.println("hello");
  }

  private HelloMain() {
    // not called. placates checkstyle
  }
}
