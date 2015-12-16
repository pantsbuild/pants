// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.jvmprepcommand;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;

/**
 * Used as an integration test for the jvm_prep_command() plugin.
 *
 * Expects the first argument to be a filename to write some data into.
 */
public class ExampleJvmPrepCommand  {
  public static void main(String args[]) throws Exception {
    if (args.length < 1) {
      throw new IllegalArgumentException("Expected filename to be passed as first argument");
    }

    File outFile = new File(args[0]);
    if (outFile.exists()) {
      outFile.delete();
    }

    PrintWriter writer = new PrintWriter(new FileOutputStream(outFile));
    try {
      writer.println("Running: " + ExampleJvmPrepCommand.class.getCanonicalName());
      writer.print("args are: ");
      for (String arg : args) {
        writer.print(String.format("\"%s\",", arg));
      }
      writer.println();
      writer.print("org.pantsbuild properties: ");
      for (String name : System.getProperties().stringPropertyNames()) {
        if (name.startsWith("org.pantsbuild")) {
          writer.print(String.format("\"%s=%s\"", name, System.getProperty(name)));
        }
      }
      writer.println();
    } finally{
      writer.close();
    }
  }
}
