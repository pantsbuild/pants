package org.pantsbuild.testproject.dummies;

import org.junit.Test;

import static org.junit.Assert.fail;


public class FailingTest {
  @Test
  public void testFail() {
    fail("I suck!");
  }
}
