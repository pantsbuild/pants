package org.pantsbuild.testproject.depman.NewTest;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** Tests that should have jersey-0.7-ea on the classpath. */
public class NewTest {

  @Test
  public void testNewIsPresent() {
    assertEquals("WadlFactory", com.sun.ws.rest.impl.wadl.WadlFactory.class.getSimpleName());
  }

  @Test(expected=ClassNotFoundException.class)
  public void testOldNotPresent() throws ClassNotFoundException {
    String notInNew = "com.sun.ws.rest.tools.webapp.writer.WebApp";
    getClass().getClassLoader().loadClass(notInNew);
  }

}
