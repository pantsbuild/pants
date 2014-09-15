// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.testproject.publish.hello.main;

import java.io.IOException;

import com.pants.testproject.publish.hello.greet.Greeting;

public class HelloMain {

  public static void main(String[] args) throws IOException {
    System.out.println("Hello");
  }

  private HelloMain() {
    // not called. placates checkstyle
  }
}
