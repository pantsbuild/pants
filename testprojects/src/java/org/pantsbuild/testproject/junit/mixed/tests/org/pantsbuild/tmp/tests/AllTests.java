package org.pantsbuild.tmp.tests;

import org.junit.Test;
import static org.junit.Assert.*;

public class AllTests {

  @Test
  public void test1Failure() {
    assertTrue(false);
  }

  @Test
  public void test2Success() {
    assertTrue(true);
  }

  @Test
  public void test3Failure() {
    assertTrue(false);
  }

  @Test
  public void test4Error() {
    throw new RuntimeException();
  }
}
