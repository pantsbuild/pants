package org.pantsbuild.tools.junit.lib;

import java.util.Arrays;
import java.util.List;
import org.junit.Assert;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;
import org.junit.runners.Parameterized.Parameters;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
@RunWith(Parameterized.class)
public class XmlReportFailingParameterizedTest {
  private String parameter;

  @Parameters
  public static List<String> data() {
    return Arrays.asList("Pass", "Fail", "ExceptionInTest", "ExceptionInConstructor");
  }

  public XmlReportFailingParameterizedTest(String parameter) {
    if ("ExceptionInConstructor".equals(parameter)) {
      throw new RuntimeException("Exception thrown from XmlReportFailingParameterizedTest()");
    }
    this.parameter = parameter;
  }

  @Test
  public void test() {
    if ("ExceptionInTest".equals(parameter)) {
      throw new RuntimeException("Exception thrown from XmlReportFailingParameterizedTest.test()");
    }
    Assert.assertEquals("Pass", parameter);
  }
}
