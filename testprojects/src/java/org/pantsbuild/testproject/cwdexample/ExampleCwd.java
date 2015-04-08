// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cwdexample;

import java.io.File;

import com.google.common.base.Joiner;

class ExampleCwd {

  private static final String EXAMPLE_SOURCE=ExampleCwd.class.getSimpleName() + ".java";
  static final String EXAMPLE_TEXT="readme.txt";

  public static boolean sourceExists() {
    File f = new File(EXAMPLE_SOURCE);
    return f.exists();
  }

  public static boolean resourceExists() {
    File f = new File(EXAMPLE_TEXT);
    return f.exists();
  }

  public static void main(String args[]) {
    if (sourceExists()) {
      System.out.println("Found " + EXAMPLE_SOURCE);
    } else if (resourceExists()) {
      System.out.println("Found " + EXAMPLE_TEXT);
    } else {
      // Including Joiner simply to get a 3rdparty jar on the classpath for testing.
      Joiner joiner = Joiner.on(" ");
      System.err.println(joiner.join(
          "Error: Neither", EXAMPLE_SOURCE,  "nor", EXAMPLE_TEXT, "found. cwd="
              + System.getProperty("user.dir")));
      System.exit(1);
    }
  }
}
