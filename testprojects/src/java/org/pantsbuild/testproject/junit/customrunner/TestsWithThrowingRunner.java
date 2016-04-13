package org.pantsbuild.testproject.junit.customrunner;

import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(ThrowingRunner.class)
public class TestsWithThrowingRunner {

  @Test
  public void test() {
    // Do nothing.
//    fail();
  }
}
