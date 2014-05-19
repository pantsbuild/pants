// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.annotation.main;

import com.pants.examples.annotation.example.Example;

/**
 * Demonstrates the use of annotation_processor()
 */
@Example("Annotation Processing Example")
public class Main {
  public static void main(String args[]) {
    System.out.println("Hello World!");
  }
}
