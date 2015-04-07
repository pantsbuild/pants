// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.java_sources;

import java.io.IOException;

import org.pantsbuild.example.scala_with_java_sources.GreetEverybody;

public class GreetMain {

  public static void main(String[] args) throws IOException {
    GreetEverybody.greetAll(args);
  }
}
