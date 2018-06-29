package org.pantsbuild.tools.junit.lib.security.threads;

import org.junit.Test;

public class DanglingThreadFromTestCase {
  @Test
  public void startedThread() {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        try {
          System.err.println("waiting 1 sec");
          Thread.sleep(1000);
          System.err.println("ending thread");
        } catch (InterruptedException e) {
          // ignored
          System.err.println("caught interrupt");
        }
      }
    });
    thread.start();
    System.err.println("got here");
  }
}
