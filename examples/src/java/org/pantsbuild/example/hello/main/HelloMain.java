// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.hello.main;

import java.io.IOException;

import org.pantsbuild.example.hello.greet.Greeting;

public class HelloMain {

  public static void main(String[] args) throws IOException {
    // Target of greeting is config'd in greetee.txt file, so read that:
    System.out.println(Greeting.greetFromFile("greetee.txt"));

    // Target of other greeting is config'd in resource, so read that:
    System.out.println(Greeting.greetFromResource("org/pantsbuild/example/hello/world.txt"));
  }

  private HelloMain() {
    // not called. placates checkstyle
  }
}
