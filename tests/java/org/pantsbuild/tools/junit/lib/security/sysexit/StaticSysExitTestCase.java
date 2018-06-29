package org.pantsbuild.tools.junit.lib.security.sysexit;

import org.junit.Test;

public class StaticSysExitTestCase {
  static {
    System.out.println("static clinit called");
    System.exit(0);
  }

  @Test
  public void passingTest() {

  }

  @Test
  public void passingTest2() {

  }
}
