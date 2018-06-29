package org.pantsbuild.tools.junit.lib.security.sysexit;

import org.junit.BeforeClass;
import org.junit.Test;

public class BeforeClassSysExitTestCase {
  @BeforeClass
  public static void before() {
    System.out.println("Calling System exit");
    System.exit(0);
  }

  @Test
  public void passingTest() {

  }

  @Test
  public void passingTest2() {

  }
}
