package org.pantsbuild.testproject.dummies;

import org.junit.Test;

public class PassingTest {
  @Test
  public void testPass1() {
    // used in JunitTestsIntegrationTest#test_junit_test_suppress_output_flag
    System.out.println("Hello from test1!");
  }

  @Test
  public void testPass2() {
    // used in JunitTestsIntegrationTest#test_junit_test_suppress_output_flag
    System.out.println("Hello from test2!");
  }

}
