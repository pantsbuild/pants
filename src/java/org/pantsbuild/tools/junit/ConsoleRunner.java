package org.pantsbuild.tools.junit;

import org.pantsbuild.tools.junit.impl.ConsoleRunnerImpl;

/**
 * Main entry point for the junit-runner task.
 *
 * All implementation classes have been moved to sub-packages to they can be shaded.
 */
public class ConsoleRunner {
  public static void main(String args[]) {
    ConsoleRunnerImpl.main(args);
  }
}
