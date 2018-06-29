// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.junit.earlyexit;

import org.junit.Test;

public class ExitInThreadStartedInTest {
  @Test
  public void testExitInJoinedThread() throws Exception {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        System.exit(0);
      }
    });
    thread.start();
    thread.join();
  }

  @Test
  public void testExitInNotJoinedThread() {
    Thread thread = new Thread(new Runnable() {
      @Override
      public void run() {
        Thread.sleep(10); // wait for test to finish.
        System.exit(0);
      }
    });
    thread.start();
  }

}
