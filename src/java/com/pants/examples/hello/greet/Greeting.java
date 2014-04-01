// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.hello.greet;

public final class Greeting {
  public static String greet(String s) {
    return "Hello, " + s + "!";
  }
  private Greeting() {
      // not called. placates checkstyle
  }
}
