package org.pantsbuild.tools.junit.lib;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;
import org.junit.runners.Parameterized.Parameters;

import static org.junit.Assert.assertTrue;


@RunWith(Parameterized.class)
public class ParameterizedTest {
  private int element;

  @Parameters(name = "{0}")
  public static Object[] data() {
    return new Integer[]{1, 2, 3, 4};
  }

  public ParameterizedTest(int element) {
    this.element = element;
  }

  @Test
  public void isLessThanFive() {
    TestRegistry.registerTestCall("isLessThanFive[" + element + "]");
    assertTrue(element < 5);
  }

  @Test
  public void isLessThanThree() {
    TestRegistry.registerTestCall("isLessThanThree[" + element + "]");
    assertTrue(element < 3);
  }
}
