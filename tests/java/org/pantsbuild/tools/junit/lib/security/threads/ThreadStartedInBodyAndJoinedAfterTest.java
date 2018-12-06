package org.pantsbuild.tools.junit.lib.security.threads;

import org.junit.AfterClass;
import org.junit.Test;

import static org.junit.Assert.fail;

public class ThreadStartedInBodyAndJoinedAfterTest {

  private static Thread thread;

  @AfterClass
  public static void joinThread() {
    System.out.println("==afterclass");
    try {
      thread.join();
    } catch (InterruptedException e) {
      e.printStackTrace();
    }
  }

  @Test
  public void passing() {
    System.out.println("==passing");
    thread = new Thread(new Runnable() {
      @Override
      public void run() {
        try {
          Thread.sleep(4);
        } catch (InterruptedException e) {
          e.printStackTrace();
        }
      }
    });
    thread.start();
  }

  @Test
  public void failing() {
    fail("failing");
  }
}
