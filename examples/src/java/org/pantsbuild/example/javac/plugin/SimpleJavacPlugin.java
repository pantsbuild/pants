// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.javac.plugin;

import com.sun.source.util.JavacTask;
import com.sun.source.util.Plugin;


/**
 * A trivial javac plugin that just prints its args.
 */
public class SimpleJavacPlugin implements Plugin {

  // Implementation of Plugin methods.

  @Override
  public String getName() {
    return SimpleJavacPluginHelper.getName();
  }

  @Override
  public void init(JavacTask task, String... args) {
    // We'd like to use String.join, but we need this to work in Java 7.
    String argsStr = "";
    for (String arg: args) {
      argsStr += (arg + " ");
    }
    System.out.println(String.format(
        "SimpleJavacPlugin ran with %d args: %s", args.length, argsStr));
  }
}
