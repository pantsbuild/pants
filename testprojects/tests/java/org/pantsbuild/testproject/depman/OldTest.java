package org.pantsbuild.testproject.depman.OldTest;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** Tests that should have jersey-0.4-ea on the classpath. */
public class OldTest {

  @Test
  public void testOldIsPresent() {
    assertEquals("WebApp", com.sun.ws.rest.tools.webapp.writer.WebApp.class.getSimpleName());
  }

  @Test(expected=ClassNotFoundException.class)
  public void testNewNotPresent() throws ClassNotFoundException {
    String notInOld = "com.sun.ws.rest.impl.wadl.WadlFactory";
    getClass().getClassLoader().loadClass(notInOld);
  }

}
