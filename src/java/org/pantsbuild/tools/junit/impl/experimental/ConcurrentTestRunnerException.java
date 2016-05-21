package org.pantsbuild.tools.junit.impl.experimental;

public class ConcurrentTestRunnerException extends RuntimeException {
  public ConcurrentTestRunnerException(String message) {
    super(message);
  }
  public ConcurrentTestRunnerException(String message, Throwable t) {
    super(message, t);
  }
}
