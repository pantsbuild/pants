package org.pantsbuild.testproject.junit.customrunner;

import org.junit.runner.Runner;
import org.junit.runner.Description;
import org.junit.runner.notification.RunNotifier;

public class ThrowingRunner extends Runner {
  public ThrowingRunner(Class ignored) {

  }

  public Description getDescription() {
    throw new RuntimeException("description");
  }

  public void run(RunNotifier notifier) {
    throw new RuntimeException("run");
  }
}