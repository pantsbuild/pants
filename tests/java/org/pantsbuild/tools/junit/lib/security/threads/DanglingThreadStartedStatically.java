package org.pantsbuild.tools.junit.lib.security.threads;

import org.junit.Test;

public class DanglingThreadStartedStatically {
  static {
    new Thread(new Runnable() {
      @Override public void run() {
        try {
          Thread.sleep(100000000);
        } catch (InterruptedException ignored) {

        }
      }
    }).start();
  }

  @Test
  public void passingTest() {

  }
}
