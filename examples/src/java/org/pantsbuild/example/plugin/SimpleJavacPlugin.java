package org.pantsbuild.example.plugin;

import com.sun.source.util.JavacTask;
import com.sun.source.util.Plugin;


/**
 * A trivial javac plugin that just prints its args.
 */
public class SimpleJavacPlugin implements Plugin {

  // Implementation of Plugin methods.

  @Override
  public String getName() {
    return "simple_javac_plugin";
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
