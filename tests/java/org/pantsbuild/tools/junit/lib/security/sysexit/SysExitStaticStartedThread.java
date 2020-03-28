package org.pantsbuild.tools.junit.lib.security.sysexit;

import org.junit.Test;

public class SysExitStaticStartedThread {
  static {
    new Thread(new Runnable() {
      @Override public void run() {
        System.exit(22);
      }
    }).start();
  }

  @Test
  public void passingTest() {

  }
}
