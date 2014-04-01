// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.hello.main;

import com.pants.examples.hello.greet.Greeting;

public class HelloMain {
  public static void main(String[] args) {
    System.out.println(Greeting.greet("world"));
  }
  private HelloMain() {
    // not called. placates checkstyle
  }
}
