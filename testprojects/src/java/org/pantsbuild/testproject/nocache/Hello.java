// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.nocache;


public class Hello {

  public static void main(String[] args) {
    System.out.println("For some reason, we don't want to cache this in the build cache");
  }
}
