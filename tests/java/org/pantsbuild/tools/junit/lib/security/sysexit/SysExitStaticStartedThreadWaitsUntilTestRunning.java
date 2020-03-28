package org.pantsbuild.tools.junit.lib.security.sysexit;

import java.util.concurrent.CountDownLatch;

import org.junit.Test;

public class SysExitStaticStartedThreadWaitsUntilTestRunning {
  public static CountDownLatch latch = new CountDownLatch(1);

  static {
    Thread thread = new Thread(new Runnable() {
      @Override public void run() {
        try {
          latch.await();
        } catch (InterruptedException ignored) {
        }
        System.out.println("thread resuming");
        System.exit(22);
      }
    });
    thread.start();
  }

  @Test
  public void passingTest1() throws InterruptedException {
    latch.countDown();
    Thread.sleep(1); // without this is flaky
  }

  @Test
  public void passingTest2() {

  }
}
