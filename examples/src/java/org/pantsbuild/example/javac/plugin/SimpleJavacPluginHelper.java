// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.javac.plugin;


/**
 * A trivial helper class, to test that plugin dependencies are handled correctly.
 */
public class SimpleJavacPluginHelper {
  public static String getName() {
    return "simple_javac_plugin";
  }
}
