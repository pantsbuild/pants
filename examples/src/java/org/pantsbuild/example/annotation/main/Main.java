// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.annotation.main;

import org.pantsbuild.example.annotation.example.Example;

/**
 * Demonstrates the use of annotation_processor()
 */
@Example("Annotation Processing Example")
public class Main {
  public static void main(String args[]) {
    System.out.println("Hello World!");
  }
}
