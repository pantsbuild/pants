package org.pantsbuild.testproject.junithamcrest;

import static org.junit.Assert.assertThat;
import org.junit.Test;

import static org.hamcrest.CoreMatchers.equalTo;


public class JUnitWithHamcrestTest {
  @Test
  public void testPass() {
    assertThat("thing", equalTo("thing"));
  }
}
