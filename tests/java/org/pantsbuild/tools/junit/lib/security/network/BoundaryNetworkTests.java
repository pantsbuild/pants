package org.pantsbuild.tools.junit.lib.security.network;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URL;
import java.net.URLConnection;
import java.util.concurrent.CountDownLatch;

import org.junit.After;
import org.junit.AfterClass;
import org.junit.Before;
import org.junit.BeforeClass;
import org.junit.Test;

public class BoundaryNetworkTests {

  public static final String NETWORK_LOCATION = "http://example.com/";
  public static String hostname = "example.com";
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

  public static void reset() {
    hostname = "example.com";
  }

  public static void setHostname(String hostname) {
    BoundaryNetworkTests.hostname = hostname;
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
  public void directNetworkCall() {
    makeNetworkCall();
    return;
  }

  private void makeNetworkCall() {
    InetSocketAddress addr = new InetSocketAddress(hostname, 80);
  }

  private void makeNetworkCall2() {
    URLConnection conn = null;
    try {
      conn = new URL(NETWORK_LOCATION).openConnection();
      conn.connect();
      conn.getOutputStream().close();
    } catch (IOException e) {
      e.printStackTrace();
    }
  }

  // this test should still fail
  @Test
  public void catchesNetworkCall() {
    try {
      makeNetworkCall();
    } catch (RuntimeException e) {
      // ignore
    }
  }

  @Test
  public void networkCallInJoinedThread() throws Exception {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        System.out.println("joined thread networkCalling");
        makeNetworkCall();
      }
    });
    thread.start();
    thread.join();
  }

  @Test
  public void networkCallInNotJoinedThread() {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        try {
          latch.await(); // wait until after AfterClass is done
          System.out.println("dangling thread done waiting");
        } catch (InterruptedException e) {
          // ignore
        }
        System.out.println("dangling thread now networkCalling");
        makeNetworkCall();
      }
    });
    thread.start();
  }

  // The network call failure should not be attributed to this test.
  @Test
  public void justSleeps() throws InterruptedException {
    Thread.sleep(10);
  }
}
