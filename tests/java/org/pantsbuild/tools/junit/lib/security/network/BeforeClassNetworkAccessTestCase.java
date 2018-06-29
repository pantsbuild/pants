package org.pantsbuild.tools.junit.lib.security.network;

import java.io.IOException;
import java.net.MalformedURLException;
import java.net.URL;
import java.net.URLConnection;

import org.junit.BeforeClass;
import org.junit.Test;

// Used for testing network access
public class BeforeClassNetworkAccessTestCase {
  @BeforeClass
  public static void before() {
    System.out.println("opening example.com");
    try {
      URL myURL = new URL("http://example.com/");
      URLConnection myURLConnection = myURL.openConnection();
      myURLConnection.connect();
      myURLConnection.getOutputStream().close();
    }
    catch (IOException e) {
      // ignore
    }
  }

  @Test
  public void passingTest() {

  }

  @Test
  public void passingTest2() {

  }
}
