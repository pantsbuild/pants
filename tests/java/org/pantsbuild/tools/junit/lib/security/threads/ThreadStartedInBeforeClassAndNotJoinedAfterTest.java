package org.pantsbuild.tools.junit.lib.security.threads;

import java.util.concurrent.CountDownLatch;

import org.junit.AfterClass;
import org.junit.BeforeClass;
import org.junit.Test;

import static org.junit.Assert.fail;

public class ThreadStartedInBeforeClassAndNotJoinedAfterTest {

  public static Thread thread;

  // this is used by the tests to stop the dangling thread after the test is over.
  public static CountDownLatch latch = new CountDownLatch(1);

  @BeforeClass
  public static void startThread() {
    System.out.println("==before.");
    thread = new Thread(new Runnable() {
      @Override
      public void run() {
        try {
          latch.await();
        } catch (InterruptedException e) {
          e.printStackTrace();
        }
      }
    });
    thread.start();
  }

  @Test
  public void passing() {

  }

  @Test
  public void failing() {
    fail("failing");
  }
}
