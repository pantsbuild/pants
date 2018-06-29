package org.pantsbuild.tools.junit.lib.security.threads;

import org.junit.After;
import org.junit.AfterClass;
import org.junit.Before;
import org.junit.BeforeClass;
import org.junit.Test;

import static org.junit.Assert.fail;

public class ThreadStartedInBeforeTest {

  private Thread thread;

  @Before
  public void startThread() {
    System.out.println("==before.");
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
  }

  @After
  public void joinThread() {
    try {
      thread.join();
    } catch (InterruptedException e) {
      e.printStackTrace();
    }
  }

  @Test
  public void passing() {

  }

  @Test
  public void failing() {
    fail("failing");
  }
}
