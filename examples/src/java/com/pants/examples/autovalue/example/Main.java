// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.autovalue.example;

/**
 * Demonstrates the use of an AutoValue produced value type.
 */
public class Main {
  public static void main(String args[]) {
    Example foo = Example.create("foo");
    System.out.println(foo.name());
  }
}
