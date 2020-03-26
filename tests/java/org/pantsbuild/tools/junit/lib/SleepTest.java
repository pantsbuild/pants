package org.pantsbuild.tools.junit.lib;

import org.junit.Test;

public class SleepTest {
  @Test
  public void sleep() throws InterruptedException {
    System.out.println("before sleep");
    Thread.sleep(10);
    System.out.println("after sleep");
    TestRegistry.registerTestCall("sleep");
  }
}
