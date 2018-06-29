package org.pantsbuild.tools.junit.lib.security.sysexit;

import java.util.concurrent.CountDownLatch;

import org.junit.After;
import org.junit.AfterClass;
import org.junit.Before;
import org.junit.BeforeClass;
import org.junit.Test;

public class BoundarySystemExitTests {

  static CountDownLatch latch = new CountDownLatch(1);

  @BeforeClass
  public static void beforeAll() {
    System.out.println("=before class.");
  }

  @AfterClass
  public static void afterAll() {
    System.out.println("=after class.");
    latch.countDown();
    try {
      Thread.sleep(1);
    } catch (InterruptedException e) {
      // ignore
    }
  }

  @Before
  public void beforeEach() {
    System.out.println("==before.");
  }

  @After
  public void afterEach() {
    System.out.println("==after.");
  }

  @Test
  public void directSystemExit() {
    System.exit(0);
  }

  // this test should still fail
  @Test
  public void catchesSystemExit() {
    try {
      System.exit(0);
    } catch (RuntimeException e) {
      // ignore
    }
  }

  @Test
  public void exitInJoinedThread() throws Exception {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        System.out.println("joined thread exiting");
        System.exit(0);
      }
    });
    thread.start();
    thread.join();
  }

  @Test
  public void exitInNotJoinedThread() {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        try {
          latch.await(); // wait until after AfterClass is done
          System.out.println("dangling thread done waiting");
        } catch (InterruptedException e) {
          // ignore
        }
        System.out.println("dangling thread now exiting");
        System.exit(0);
      }
    });
    thread.start();
  }

  // The system exit failure should not be attributed to this test.
  @Test
  public void justSleeps() throws InterruptedException {
    Thread.sleep(10);
  }
}
