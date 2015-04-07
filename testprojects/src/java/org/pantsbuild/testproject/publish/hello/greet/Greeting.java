// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.publish.hello.greet;

import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Scanner;

public final class Greeting {
  public static String greetFromFile(String filename) throws IOException {
    FileInputStream is = new FileInputStream(filename);
    try {
      return greetFromStream(is);
    } finally {
      is.close();
    }
  }

  public static String greetFromResource(String resource) throws IOException {
    InputStream is = Greeting.class.getClassLoader().getResourceAsStream(resource);
    try {
      return greetFromStream(is);
    } finally {
      is.close();
    }
  }

  public static String greetFromStream(InputStream is) throws IOException {
    return greet(new Scanner(is).useDelimiter("\\Z").next());
  }

  public static String greet(String greetee) {
    return String.format("Hello, %s!", greetee);
  }

  private Greeting() {
    // not called. placates checkstyle
  }
}
