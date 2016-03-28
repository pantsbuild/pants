package org.pantsbuild.tmp.tests;

import org.junit.Test;

import static org.junit.Assert.assertTrue;

public class InnerClassTests {
  public static class InnerClassSuccessTest {
    @Test
    public void testInnerSuccess() {
      assertTrue(true);
    }
  }

  public static class InnerClassFailureTest {
    @Test
    public void testInnerFailure() {
      assertTrue(false);
    }

    @Test
    public void testInnerSuccess() {
      assertTrue(true);
    }
  }

  public static class InnerInnerTest {
    @Test
    public void testSuccess() {
      assertTrue(true);
    }

    public static class InnerFailureTest {
      @Test
      public void testFailure() {
        assertTrue(false);
      }
    }
  }
}
