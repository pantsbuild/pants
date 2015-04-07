package org.pantsbuild.testing.protolib;

import junit.framework.Test;
import junit.framework.TestCase;
import junit.framework.TestSuite;
import com.squareup.testing.protolib.A;

/**
 * Unit test for protos defined in protolib-test artifact.
 */
public class ProtolibTest
    extends TestCase {
  /**
   * Create the test case
   *
   * @param testName name of the test case
   */
  public ProtolibTest(String testName) {
    super(testName);
  }

  /**
   * @return the suite of tests being tested
   */
  public static Test suite() {
    return new TestSuite(ProtolibTest.class);
  }

  /**
   * Rigorous Test :-)
   */
  public void testApp() {
    A.AMessage message = A.AMessage.newBuilder().setExample("&").setUnicode('&').build();
    assertTrue(message.getExample().equals("&"));
  }
}
